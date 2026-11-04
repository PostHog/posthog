import { EventEmitter } from 'events'

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

        const blocked = await service.getBlockedRecipients(team.id, [address])

        expect(blocked).toEqual(
            expected === 'allowed' ? [] : [{ address, unverifiedMember: expected === 'unverified' }]
        )
    })

    it('blocks a verified member of another organization', async () => {
        const otherOrganizationId = await createOrganization(hub.postgres)
        const outsider = `outsider-${team.id}@example.com`
        await createMember(outsider, otherOrganizationId, true)
        await createMember(memberEmail, organizationId, true)

        expect(await service.getBlockedRecipients(team.id, [memberEmail, outsider])).toEqual([
            { address: outsider, unverifiedMember: false },
        ])
    })

    type FakeClient = EventEmitter & { query: jest.Mock; release: jest.Mock }

    it.each([
        ['the pool hands over its connection after the deadline', { connectsLate: true, beginStalls: false }],
        ['BEGIN stalls on a connection taken in time', { connectsLate: false, beginStalls: true }],
    ])('fails at its deadline when %s, and frees the connection', async (_case, { connectsLate, beginStalls }) => {
        jest.useFakeTimers()
        try {
            const client = Object.assign(new EventEmitter(), {
                query: jest.fn(() => (beginStalls ? new Promise(() => undefined) : Promise.resolve({ rows: [] }))),
                release: jest.fn(),
            }) as FakeClient
            let handOver: () => void = () => undefined
            const connected = connectsLate ? new Promise<void>((resolve) => (handOver = resolve)) : Promise.resolve()
            const router = new PostgresRouter({ DATABASE_URL: 'postgres://fake', POSTGRES_CONNECTION_POOL_SIZE: 1 })
            ;(router as any).pools = new Map([
                [PostgresUse.COMMON_WRITE, { connect: () => connected.then(() => client) }],
            ])
            const stalledService = new OrganizationMembersService(router)

            const check = stalledService.getBlockedRecipients(team.id, [memberEmail])
            const outcome = expect(check).rejects.toThrow('The organization member lookup timed out')
            await jest.advanceTimersByTimeAsync(3_000)
            await outcome
            handOver()
            await jest.advanceTimersByTimeAsync(0)

            expect(client.query.mock.calls.map(([sql]) => sql)).toEqual(connectsLate ? [] : ['BEGIN'])
            expect(client.release).toHaveBeenCalledTimes(1)
            expect(client.release.mock.calls[0][0] instanceof Error).toBe(!connectsLate)
        } finally {
            jest.useRealTimers()
        }
    })
})
