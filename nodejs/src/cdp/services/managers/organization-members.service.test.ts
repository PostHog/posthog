import { PostgresRouter } from '~/common/utils/db/postgres'

import { OrganizationMembersService } from './organization-members.service'

describe('OrganizationMembersService', () => {
    const queriesPerLookup = 2
    const memberRow = (email: string): { team_id: number; email: string; is_email_verified: boolean } => ({
        team_id: 1,
        email,
        is_email_verified: true,
    })
    const rowsFor = (name: string, member: string): { rows: unknown[] } => ({
        rows: name === 'fetch-sandbox-team-organization-members' ? [memberRow(member)] : [],
    })
    const allowed = { organizationBlocked: false, blockedRecipients: [] }

    it('fails closed when every member lookup outlasts its one-minute decision', async () => {
        let now = 0
        const query = jest.fn((_use: unknown, _sql: string, _params: unknown, name: string) => {
            now += 60_000
            return Promise.resolve(rowsFor(name, 'member@example.com'))
        })
        const service = new OrganizationMembersService({ query } as unknown as PostgresRouter, () => now)

        await expect(service.checkRecipients(1, ['member@example.com'])).rejects.toThrow('expired')
        expect(query).toHaveBeenCalledTimes(2 * queriesPerLookup)
    })

    it('shares one member lookup across sends and reloads it after a minute', async () => {
        let now = 0
        let member = 'member@example.com'
        const query = jest.fn((_use: unknown, _sql: string, _params: unknown, name: string) =>
            Promise.resolve(rowsFor(name, member))
        )
        const service = new OrganizationMembersService({ query } as unknown as PostgresRouter, () => now)

        expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(allowed)
        expect(await service.checkRecipients(1, ['member@example.com'])).toEqual(allowed)
        expect(query).toHaveBeenCalledTimes(queriesPerLookup)

        now = 60_001
        member = 'new-member@example.com'
        expect(await service.checkRecipients(1, ['member@example.com'])).toEqual({
            organizationBlocked: false,
            blockedRecipients: [{ address: 'member@example.com', unverifiedMember: false }],
        })
        expect(query).toHaveBeenCalledTimes(2 * queriesPerLookup)
    })
})
