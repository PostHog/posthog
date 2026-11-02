import { PostgresRouter } from '~/common/utils/db/postgres'

import { OrganizationMembersService } from './organization-members.service'

describe('OrganizationMembersService', () => {
    const memberRow = (email: string): { team_id: number; email: string; is_email_verified: boolean } => ({
        team_id: 1,
        email,
        is_email_verified: true,
    })

    it('fails closed when every member lookup outlasts its one-minute decision', async () => {
        let now = 0
        const query = jest.fn(() => {
            now += 60_000
            return Promise.resolve({ rows: [memberRow('member@example.com')] })
        })
        const service = new OrganizationMembersService({ query } as unknown as PostgresRouter, () => now)

        await expect(service.getBlockedRecipients(1, ['member@example.com'])).rejects.toThrow('expired')
        expect(query).toHaveBeenCalledTimes(2)
    })

    it('shares one member lookup across sends and reloads it after a minute', async () => {
        let now = 0
        let member = 'member@example.com'
        const query = jest.fn(() => Promise.resolve({ rows: [memberRow(member)] }))
        const service = new OrganizationMembersService({ query } as unknown as PostgresRouter, () => now)

        expect(await service.getBlockedRecipients(1, ['member@example.com'])).toEqual([])
        expect(await service.getBlockedRecipients(1, ['member@example.com'])).toEqual([])
        expect(query).toHaveBeenCalledTimes(1)

        now = 60_001
        member = 'new-member@example.com'
        expect(await service.getBlockedRecipients(1, ['member@example.com'])).toEqual([
            { address: 'member@example.com', unverifiedMember: false },
        ])
        expect(query).toHaveBeenCalledTimes(2)
    })
})
