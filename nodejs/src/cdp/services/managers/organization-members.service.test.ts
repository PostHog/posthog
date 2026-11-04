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

            const check = stalledService.getBlockedRecipients(team.id, [memberEmail])
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
})
