import { EventEmitter } from 'events'
import { PoolClient } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import {
    createOrganization,
    createOrganizationMembership,
    createTestTeamFixture,
    createUser,
} from '~/tests/helpers/sql'
import { Team } from '~/types'

import { OrganizationMembersService, RecipientCheck } from './organization-members.service'

const idleClient = (): unknown => ({
    query: () => Promise.resolve({ rows: [] }),
    release: () => undefined,
    on: () => undefined,
    removeListener: () => undefined,
})

const blockQueryTag = 'fetch-sandbox-team-organization-blocks'

const routerFor = (select: jest.Mock, blockedTeamIds: () => number[] = () => []): PostgresRouter =>
    ({
        connect: () => Promise.resolve(idleClient()),
        query: (_tx: unknown, sql: string, _params: unknown, tag: string) =>
            sql.startsWith('SET LOCAL')
                ? Promise.resolve({ rows: [] })
                : tag === blockQueryTag
                  ? Promise.resolve({ rows: blockedTeamIds().map((team_id) => ({ team_id })) })
                  : select(),
    }) as unknown as PostgresRouter

const memberCheck = (check: RecipientCheck): Extract<RecipientCheck, { organizationBlocked: false }> => {
    if (check.organizationBlocked) {
        throw new Error('The organization is blocked')
    }
    return check
}

describe('OrganizationMembersService', () => {
    let postgres: PostgresRouter
    let service: OrganizationMembersService
    let team: Team
    let organizationId: string
    let memberEmail: string

    const createMember = async (email: string, inOrganization: string, verified: boolean | null): Promise<number> => {
        const userId = await createUser(postgres, new UUIDT().toString())
        await createOrganizationMembership(postgres, inOrganization, userId)
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            'UPDATE posthog_user SET email = $1, is_active = true, is_email_verified = $2 WHERE id = $3',
            [email, verified, userId],
            'test:create-sandbox-member'
        )
        return userId
    }

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)
        service = new OrganizationMembersService(postgres)
        ;({ team, organizationId } = await createTestTeamFixture(postgres))
        memberEmail = `member-${team.id}@example.com`
    })

    afterEach(async () => {
        await postgres.end()
    })

    it.each([
        ['allows a verified member, whatever the case and padding', true, () => Promise.resolve(), 'allowed'],
        ['flags an unverified member', false, () => Promise.resolve(), 'unverified'],
        ['flags a member with no recorded verification as unverified', null, () => Promise.resolve(), 'unverified'],
        [
            'blocks a removed member',
            true,
            (userId: number) =>
                postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_organizationmembership WHERE user_id = $1',
                    [userId],
                    'test:remove-sandbox-member'
                ),
            'blocked',
        ],
        [
            'blocks an inactive member',
            true,
            (userId: number) =>
                postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_user SET is_active = false WHERE id = $1',
                    [userId],
                    'test:deactivate-sandbox-member'
                ),
            'blocked',
        ],
        [
            'blocks every member of an inactive organization',
            true,
            () =>
                postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_organization SET is_active = false WHERE id = $1',
                    [organizationId],
                    'test:deactivate-sandbox-organization'
                ),
            'blocked',
        ],
        [
            'blocks every recipient once staff block the organization',
            true,
            () =>
                postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO workflows_sandboxsenderorganizationblock (organization_id, reason, created_at)
                     VALUES ($1, 'test block', now())`,
                    [organizationId],
                    'test:block-sandbox-organization'
                ),
            'organization_blocked',
        ],
    ] as const)('%s', async (_case, verified, change, expected) => {
        const userId = await createMember(memberEmail, organizationId, verified)
        await change(userId)
        const address = `  ${memberEmail.toUpperCase()} `

        const check = await service.checkRecipients(team.id, [address], { fresh: false })

        expect(check).toEqual(
            expected === 'organization_blocked'
                ? { organizationBlocked: true }
                : expected === 'allowed'
                  ? { organizationBlocked: false, blocked: [], deliverTo: new Map([[address, memberEmail]]) }
                  : {
                        organizationBlocked: false,
                        blocked: [{ address, unverifiedMember: expected === 'unverified' }],
                        deliverTo: new Map(),
                    }
        )
    })

    it('blocks a verified member of another organization', async () => {
        const otherOrganizationId = await createOrganization(postgres)
        const outsider = `outsider-${team.id}@example.com`
        await createMember(outsider, otherOrganizationId, true)
        await createMember(memberEmail, organizationId, true)

        expect(await service.checkRecipients(team.id, [memberEmail, outsider], { fresh: false })).toEqual({
            organizationBlocked: false,
            blocked: [{ address: outsider, unverifiedMember: false }],
            deliverTo: new Map([[memberEmail, memberEmail]]),
        })
    })

    it.each([
        ['delivers to the address that matches one exactly', ['Member', 'member'], 'Member', 'Member'],
        ['blocks an address that matches neither', ['Member', 'member'], 'MEMBER', undefined],
        [
            'delivers to the one stored address when padding is all they differ by',
            ['member', ' member'],
            'MEMBER',
            'member',
        ],
    ])('%s of two members whose stored addresses differ', async (_case, stored, written, delivered) => {
        for (const name of stored) {
            await createMember(`${name}-${team.id}@example.com`, organizationId, true)
        }
        const address = `${written}-${team.id}@example.com`
        const deliveredAddress = delivered && `${delivered}-${team.id}@example.com`

        const check = memberCheck(await service.checkRecipients(team.id, [address], { fresh: false }))

        expect(check.deliverTo.get(address)).toBe(deliveredAddress)
        expect(check.blocked).toEqual(deliveredAddress ? [] : [{ address, unverifiedMember: false }])
    })

    type FakeClient = EventEmitter & { query: jest.Mock; release: jest.Mock }

    it.each([
        ['the pool hands over its connections after the deadline', { connectsLate: true, beginStalls: false }],
        ['BEGIN stalls on connections taken in time', { connectsLate: false, beginStalls: true }],
    ])(
        'fails at its deadline when %s, frees each connection, and leaves its lookup slots to the next check',
        async (_case, { connectsLate, beginStalls }) => {
            jest.useFakeTimers()
            try {
                let healthy = false
                const clients: FakeClient[] = []
                const newClient = (): FakeClient => {
                    const stalls = beginStalls && !healthy
                    const client = Object.assign(new EventEmitter(), {
                        query: jest.fn(() => (stalls ? new Promise(() => undefined) : Promise.resolve({ rows: [] }))),
                        release: jest.fn(),
                    }) as FakeClient
                    clients.push(client)
                    return client
                }
                let handOver: () => void = () => undefined
                const connected = connectsLate
                    ? new Promise<void>((resolve) => (handOver = resolve))
                    : Promise.resolve()
                const router = new PostgresRouter({ DATABASE_URL: 'postgres://fake', POSTGRES_CONNECTION_POOL_SIZE: 1 })
                jest.spyOn(router, 'connect').mockImplementation(() =>
                    (healthy ? Promise.resolve() : connected).then(() => newClient() as unknown as PoolClient)
                )
                const stalledService = new OrganizationMembersService(router)

                const checks = Promise.allSettled(
                    Array.from({ length: 5 }, () =>
                        stalledService.checkRecipients(team.id, [memberEmail], { fresh: true })
                    )
                )
                await jest.advanceTimersByTimeAsync(3_000)
                expect((await checks).map((outcome) => outcome.status)).toEqual(Array(5).fill('rejected'))
                handOver()
                await jest.advanceTimersByTimeAsync(0)

                expect(clients.map((client) => client.query.mock.calls.map(([sql]) => sql))).toEqual(
                    Array(5).fill(connectsLate ? [] : ['BEGIN'])
                )
                expect(
                    clients.map((client) => client.release.mock.calls.map(([error]) => error instanceof Error))
                ).toEqual(Array(5).fill([!connectsLate]))

                healthy = true
                const next = stalledService.checkRecipients(team.id, [memberEmail], { fresh: true })
                await jest.advanceTimersByTimeAsync(0)
                await expect(next).resolves.toEqual({
                    organizationBlocked: false,
                    blocked: [{ address: memberEmail, unverifiedMember: false }],
                    deliverTo: new Map(),
                })
            } finally {
                jest.useRealTimers()
            }
        }
    )

    describe('member snapshot cache', () => {
        const memberRow = (email: string): { team_id: number; email: string; is_email_verified: boolean } => ({
            team_id: 1,
            email,
            is_email_verified: true,
        })

        it('keeps at most five lookups open while the pool has no connection, and runs no query for them once it recovers', async () => {
            jest.useFakeTimers()
            try {
                let recovered = false
                const waitingForConnection: (() => void)[] = []
                const lateClients: { query: jest.Mock; release: jest.Mock }[] = []
                const lateClient = (): unknown => {
                    const client = { ...(idleClient() as object), query: jest.fn(), release: jest.fn() }
                    lateClients.push(client)
                    return client
                }
                const query = jest.fn((_tx: unknown, sql: string, _params: unknown, tag: string) =>
                    Promise.resolve({
                        rows:
                            sql.startsWith('SET LOCAL') || tag === blockQueryTag
                                ? []
                                : [memberRow('member@example.com')],
                    })
                )
                const memberSelects = (): number =>
                    query.mock.calls.filter(([, sql]) => String(sql).includes('posthog_organizationmembership')).length
                const pool = {
                    connect: () =>
                        recovered
                            ? Promise.resolve(idleClient())
                            : new Promise((resolve) => waitingForConnection.push(() => resolve(lateClient()))),
                    query,
                } as unknown as PostgresRouter
                const service = new OrganizationMembersService(pool)

                const checks = Array.from({ length: 20 }, () =>
                    service.checkRecipients(1, ['member@example.com'], { fresh: true })
                )
                const outcomes = Promise.allSettled(checks)
                await jest.advanceTimersByTimeAsync(3_000)

                const settled = await outcomes
                expect(settled.every((outcome) => outcome.status === 'rejected')).toBe(true)
                expect(waitingForConnection).toHaveLength(5)

                recovered = true
                waitingForConnection.forEach((connect) => connect())
                await jest.advanceTimersByTimeAsync(0)
                expect(query).not.toHaveBeenCalled()
                expect(
                    lateClients.map((client) => [client.query.mock.calls.length, client.release.mock.calls.length])
                ).toEqual(Array(5).fill([0, 1]))

                await expect(
                    service.checkRecipients(1, ['member@example.com'], { fresh: true })
                ).resolves.toMatchObject({ blocked: [] })
                expect(memberSelects()).toBe(1)
            } finally {
                jest.useRealTimers()
            }
        })

        it('shares one member lookup with a send that starts while it runs and with later sends, and reloads it before it is a minute old', async () => {
            const start = Date.now()
            const clock = jest.spyOn(Date, 'now').mockReturnValue(start)
            let member = 'member@example.com'
            let lookups = 0
            let lookupStarted: () => void = () => {}
            const started = new Promise<void>((resolve) => {
                lookupStarted = resolve
            })
            let releaseLookup: () => void = () => {}
            const held = new Promise<void>((resolve) => {
                releaseLookup = resolve
            })
            const query = jest.fn(async () => {
                lookups++
                if (lookups === 1) {
                    lookupStarted()
                    await held
                }
                return { rows: [memberRow(member)] }
            })
            const service = new OrganizationMembersService(routerFor(query))
            try {
                const first = service.checkRecipients(1, ['member@example.com'], { fresh: false })
                await started
                const joining = service.checkRecipients(1, ['member@example.com'], { fresh: false })
                releaseLookup()
                expect((await Promise.all([first, joining])).map((check) => memberCheck(check).blocked)).toEqual([
                    [],
                    [],
                ])
                expect(
                    memberCheck(await service.checkRecipients(1, ['member@example.com'], { fresh: false })).blocked
                ).toEqual([])
                expect(query).toHaveBeenCalledTimes(1)

                clock.mockReturnValue(start + 57_001)
                member = 'new-member@example.com'
                expect(
                    memberCheck(await service.checkRecipients(1, ['member@example.com'], { fresh: false })).blocked
                ).toEqual([{ address: 'member@example.com', unverifiedMember: false }])
            } finally {
                clock.mockRestore()
            }
        })

        type Lookup = { member: string; blockedTeamIds: number[] }

        it.each([
            [
                'the member is removed',
                (lookup: Lookup): void => {
                    lookup.member = 'new-member@example.com'
                },
                [{ address: 'member@example.com', unverifiedMember: false }],
            ],
            [
                'staff block the organization',
                (lookup: Lookup): void => {
                    lookup.blockedTeamIds = [1]
                },
                'organization blocked',
            ],
        ] as const)(
            'reloads a fresh check inside the minute when %s, and blocks later cached checks as well',
            async (_case, change, expected) => {
                const lookup: Lookup = { member: 'member@example.com', blockedTeamIds: [] }
                const query = jest.fn(() => Promise.resolve({ rows: [memberRow(lookup.member)] }))
                const service = new OrganizationMembersService(routerFor(query, () => lookup.blockedTeamIds))
                const outcome = (check: RecipientCheck): unknown =>
                    check.organizationBlocked ? 'organization blocked' : check.blocked

                expect(outcome(await service.checkRecipients(1, ['member@example.com'], { fresh: false }))).toEqual([])
                change(lookup)

                expect(outcome(await service.checkRecipients(1, ['member@example.com'], { fresh: true }))).toEqual(
                    expected
                )
                expect(outcome(await service.checkRecipients(1, ['member@example.com'], { fresh: false }))).toEqual(
                    expected
                )
            }
        )

        it('reloads a cached block older than five seconds before reporting it, and reuses the reload for later blocks', async () => {
            const start = Date.now()
            const clock = jest.spyOn(Date, 'now').mockReturnValue(start)
            let members = ['member@example.com']
            const query = jest.fn(() => Promise.resolve({ rows: members.map(memberRow) }))
            const service = new OrganizationMembersService(routerFor(query))
            const outsider = [{ address: 'outside@example.com', unverifiedMember: false }]
            const blocked = async (address: string): Promise<unknown> =>
                memberCheck(await service.checkRecipients(1, [address], { fresh: false })).blocked
            try {
                expect(await blocked('member@example.com')).toEqual([])
                members = ['member@example.com', 'joined@example.com']
                clock.mockReturnValue(start + 5_001)

                expect(await blocked('joined@example.com')).toEqual([])
                expect(await blocked('outside@example.com')).toEqual(outsider)
                expect(await blocked('outside@example.com')).toEqual(outsider)
                expect(query).toHaveBeenCalledTimes(2)
            } finally {
                clock.mockRestore()
            }
        })

        it('shares one reload between blocked sends that arrive while it runs', async () => {
            jest.useFakeTimers()
            const start = Date.now()
            let reloadStarted: () => void = () => {}
            const started = new Promise<void>((resolve) => (reloadStarted = resolve))
            let releaseReload: () => void = () => {}
            const held = new Promise<void>((resolve) => (releaseReload = resolve))
            const query = jest
                .fn()
                .mockResolvedValueOnce({ rows: [memberRow('member@example.com')] })
                .mockImplementation(async () => {
                    reloadStarted()
                    await held
                    return { rows: [memberRow('member@example.com')] }
                })
            const service = new OrganizationMembersService(routerFor(query))
            const outsider = [{ address: 'outside@example.com', unverifiedMember: false }]
            try {
                const firstLoad = service.getBlockedRecipients(1, ['member@example.com'], { fresh: false })
                await jest.advanceTimersByTimeAsync(0)
                expect(await firstLoad).toEqual([])
                jest.setSystemTime(start + 5_001)

                const first = service.getBlockedRecipients(1, ['outside@example.com'], { fresh: false })
                await jest.advanceTimersByTimeAsync(0)
                await started
                const later = Array.from({ length: 5 }, () =>
                    service.getBlockedRecipients(1, ['outside@example.com'], { fresh: false })
                )
                await jest.advanceTimersByTimeAsync(0)
                expect(query).toHaveBeenCalledTimes(2)

                releaseReload()
                await jest.advanceTimersByTimeAsync(0)
                expect(await Promise.all([first, ...later])).toEqual(Array(6).fill(outsider))
            } finally {
                jest.useRealTimers()
            }
        })

        it('keeps serving the cached members to later sends when the reload of a cached block fails', async () => {
            const start = Date.now()
            const clock = jest.spyOn(Date, 'now').mockReturnValue(start)
            const query = jest
                .fn()
                .mockResolvedValueOnce({ rows: [memberRow('member@example.com')] })
                .mockRejectedValue(new Error('primary unavailable'))
            const service = new OrganizationMembersService(routerFor(query))
            const blocked = async (address: string): Promise<unknown> =>
                memberCheck(await service.checkRecipients(1, [address], { fresh: false })).blocked
            try {
                expect(await blocked('member@example.com')).toEqual([])
                clock.mockReturnValue(start + 5_001)

                await expect(blocked('outside@example.com')).rejects.toThrow()
                expect(await blocked('member@example.com')).toEqual([])
                expect(query).toHaveBeenCalledTimes(2)
            } finally {
                clock.mockRestore()
            }
        })

        it('does not let a fresh check join a lookup that started before it', async () => {
            let finishEarlierLookup: (rows: unknown) => void = () => {}
            const query = jest
                .fn()
                .mockReturnValueOnce(new Promise((resolve) => (finishEarlierLookup = resolve)))
                .mockResolvedValue({ rows: [memberRow('new-member@example.com')] })
            const service = new OrganizationMembersService(routerFor(query))

            const earlierCheck = service.checkRecipients(1, ['member@example.com'], { fresh: false })
            while (query.mock.calls.length === 0) {
                await new Promise((resolve) => setImmediate(resolve))
            }
            const freshCheck = service.checkRecipients(1, ['member@example.com'], { fresh: true })
            finishEarlierLookup({ rows: [memberRow('member@example.com')] })

            expect(memberCheck(await earlierCheck).blocked).toEqual([])
            expect(memberCheck(await freshCheck).blocked).toEqual([
                { address: 'member@example.com', unverifiedMember: false },
            ])
            expect(query).toHaveBeenCalledTimes(2)
        })
    })
})
