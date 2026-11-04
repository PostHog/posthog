import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import {
    createOrganization,
    createOrganizationMembership,
    createTestTeamFixture,
    createUser,
} from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { OrganizationMembersService } from './organization-members.service'

const blockQueryTag = 'fetch-sandbox-team-organization-blocks'

const routerFor = (select: jest.Mock, blockedTeamIds: () => number[] = () => []): PostgresRouter =>
    ({
        transaction: (_usage: unknown, _tag: string, run: (tx: unknown) => Promise<unknown>) => run({}),
        query: (_tx: unknown, sql: string, _params: unknown, tag: string) =>
            sql.startsWith('SET LOCAL')
                ? Promise.resolve({ rows: [] })
                : tag === blockQueryTag
                  ? Promise.resolve({ rows: blockedTeamIds().map((team_id) => ({ team_id })) })
                  : select(),
    }) as unknown as PostgresRouter

describe('OrganizationMembersService', () => {
    let hub: Hub
    let service: OrganizationMembersService
    let team: Team
    let organizationId: string
    let memberEmail: string

    const createMember = async (email: string, inOrganization: string, verified: boolean | null): Promise<number> => {
        const userId = await createUser(hub.postgres, new UUIDT().toString())
        await createOrganizationMembership(hub.postgres, inOrganization, userId)
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            'UPDATE posthog_user SET email = $1, is_active = true, is_email_verified = $2 WHERE id = $3',
            [email, verified, userId],
            'test:create-sandbox-member'
        )
        return userId
    }

    beforeEach(async () => {
        hub = await createHub()
        service = new OrganizationMembersService(hub.postgres)
        ;({ team, organizationId } = await createTestTeamFixture(hub.postgres))
        memberEmail = `member-${team.id}@example.com`
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it.each([
        ['allows a verified member, whatever the case and padding', true, () => Promise.resolve(), 'allowed'],
        ['flags an unverified member', false, () => Promise.resolve(), 'unverified'],
        ['flags a member with no recorded verification as unverified', null, () => Promise.resolve(), 'unverified'],
        [
            'blocks a removed member',
            true,
            (userId: number) =>
                hub.postgres.query(
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
                hub.postgres.query(
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
                hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_organization SET is_active = false WHERE id = $1',
                    [organizationId],
                    'test:deactivate-sandbox-organization'
                ),
            'blocked',
        ],
    ] as const)('%s', async (_case, verified, change, expected) => {
        const userId = await createMember(memberEmail, organizationId, verified)
        await change(userId)
        const address = `  ${memberEmail.toUpperCase()} `

        const check = await service.checkRecipients(team.id, [address])

        expect(check).toEqual(
            expected === 'allowed'
                ? { organizationBlocked: false, blocked: [], deliverTo: [memberEmail] }
                : {
                      organizationBlocked: false,
                      blocked: [{ address, unverifiedMember: expected === 'unverified' }],
                      deliverTo: [],
                  }
        )
    })

    it('blocks a verified member of another organization', async () => {
        const otherOrganizationId = await createOrganization(hub.postgres)
        const outsider = `outsider-${team.id}@example.com`
        await createMember(outsider, otherOrganizationId, true)
        await createMember(memberEmail, organizationId, true)

        expect(await service.checkRecipients(team.id, [memberEmail, outsider])).toEqual({
            organizationBlocked: false,
            blocked: [{ address: outsider, unverifiedMember: false }],
            deliverTo: [memberEmail],
        })
    })

    it('blocks every recipient once staff block the organization', async () => {
        await createMember(memberEmail, organizationId, true)
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO workflows_sandboxsenderorganizationblock (organization_id, reason, created_at)
             VALUES ($1, 'test block', now())`,
            [organizationId],
            'test:block-sandbox-organization'
        )

        expect(await service.checkRecipients(team.id, [memberEmail])).toEqual({ organizationBlocked: true })
    })

    it('fails at its deadline when the lookup waits for a connection, and runs no query once it gets one', async () => {
        jest.useFakeTimers()
        try {
            let connect: (() => void) | undefined
            const query = jest.fn()
            const stalledPostgres = {
                transaction: (_usage: unknown, _tag: string, run: (tx: unknown) => Promise<unknown>) =>
                    new Promise((resolve, reject) => {
                        connect = () => void run({}).then(resolve, reject)
                    }),
                query,
            } as unknown as PostgresRouter
            const stalledService = new OrganizationMembersService(stalledPostgres)

            const check = stalledService.checkRecipients(team.id, [memberEmail])
            const outcome = expect(check).rejects.toThrow('The organization member lookup timed out')
            await jest.advanceTimersByTimeAsync(3_000)

            await outcome
            connect?.()
            await jest.advanceTimersByTimeAsync(0)
            expect(query).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
        }
    })

    describe('member snapshot cache', () => {
        const memberRow = (email: string): { team_id: number; email: string; is_email_verified: boolean } => ({
            team_id: 1,
            email,
            is_email_verified: true,
        })
        const allowed = { organizationBlocked: false, blocked: [], deliverTo: ['member@example.com'] }
        const memberBlocked = {
            organizationBlocked: false,
            blocked: [{ address: 'member@example.com', unverifiedMember: false }],
            deliverTo: [],
        }

        it('fails closed when every member lookup outlasts its one-minute decision', async () => {
            let now = 0
            const query = jest.fn(() => {
                now += 60_000
                return Promise.resolve({ rows: [memberRow('member@example.com')] })
            })
            const service = new OrganizationMembersService(routerFor(query), () => now)

            await expect(service.checkRecipients(1, ['member@example.com'])).rejects.toThrow('expired')
            expect(query).toHaveBeenCalledTimes(2)
        })

        it('fails closed when the fresh lookup outlasts its one-minute decision', async () => {
            let now = 0
            const query = jest.fn(() => {
                now += 60_000
                return Promise.resolve({ rows: [memberRow('member@example.com')] })
            })
            const service = new OrganizationMembersService(routerFor(query), () => now)

            await expect(service.checkRecipients(1, ['member@example.com'], { fresh: true })).rejects.toThrow('expired')
            expect(query).toHaveBeenCalledTimes(1)
        })

        it('keeps at most five lookups open while the pool has no connection, and runs no query for them once it recovers', async () => {
            jest.useFakeTimers()
            try {
                let recovered = false
                const waitingForConnection: (() => void)[] = []
                const query = jest.fn((_tx: unknown, sql: string, _params: unknown, tag: string) =>
                    Promise.resolve({
                        rows:
                            sql.startsWith('SET LOCAL') || tag === blockQueryTag
                                ? []
                                : [memberRow('member@example.com')],
                    })
                )
                const pool = {
                    transaction: (_usage: unknown, _tag: string, run: (tx: unknown) => Promise<unknown>) =>
                        recovered
                            ? run({})
                            : new Promise((resolve, reject) =>
                                  waitingForConnection.push(() => void run({}).then(resolve, reject))
                              ),
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

                await expect(service.checkRecipients(1, ['member@example.com'], { fresh: true })).resolves.toEqual(
                    allowed
                )
                expect(query).toHaveBeenCalledTimes(3)
            } finally {
                jest.useRealTimers()
            }
        })

        it('shares one member lookup across sends and reloads it after a minute', async () => {
            let now = 0
            let member = 'member@example.com'
            const query = jest.fn(() => Promise.resolve({ rows: [memberRow(member)] }))
            const service = new OrganizationMembersService(routerFor(query), () => now)

            expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(allowed)
            expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(allowed)
            expect(query).toHaveBeenCalledTimes(1)

            now = 60_001
            member = 'new-member@example.com'
            expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(memberBlocked)
            expect(query).toHaveBeenCalledTimes(2)
        })

        it.each([
            ['the member is removed', memberBlocked],
            ['the organization is blocked', { organizationBlocked: true }],
        ])('reloads a fresh check inside the minute when %s', async (change, expected) => {
            let member = 'member@example.com'
            let blockedTeamIds: number[] = []
            const query = jest.fn(() => Promise.resolve({ rows: [memberRow(member)] }))
            const service = new OrganizationMembersService(
                routerFor(query, () => blockedTeamIds),
                () => 0
            )

            expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(allowed)
            if (change === 'the member is removed') {
                member = 'new-member@example.com'
            } else {
                blockedTeamIds = [1]
            }

            expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(allowed)
            expect(await service.checkRecipients(1, ['member@example.com'], { fresh: true })).toEqual(expected)
            expect(query).toHaveBeenCalledTimes(2)
        })

        it('does not let a fresh check join a lookup that started before it', async () => {
            let finishEarlierLookup: (rows: unknown) => void = () => {}
            const query = jest
                .fn()
                .mockReturnValueOnce(new Promise((resolve) => (finishEarlierLookup = resolve)))
                .mockResolvedValue({ rows: [memberRow('new-member@example.com')] })
            const service = new OrganizationMembersService(routerFor(query), () => 0)

            // Another send starts loading members, then the member is removed before the final check.
            const earlierCheck = service.checkRecipients(1, ['member@example.com'])
            while (query.mock.calls.length === 0) {
                await new Promise((resolve) => setImmediate(resolve))
            }
            const freshCheck = service.checkRecipients(1, ['member@example.com'], { fresh: true })
            finishEarlierLookup({ rows: [memberRow('member@example.com')] })

            expect(await earlierCheck).toEqual(allowed)
            expect(await freshCheck).toEqual(memberBlocked)
            expect(query).toHaveBeenCalledTimes(2)
        })
    })
})
