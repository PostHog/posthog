import { PostgresRouter } from '~/common/utils/db/postgres'

import { OrganizationMembersService } from './organization-members.service'

const routerFor = (select: jest.Mock): PostgresRouter =>
    ({
        transaction: (_usage: unknown, _tag: string, run: (tx: unknown) => Promise<unknown>) => run({}),
        query: (_tx: unknown, sql: string) => (sql.startsWith('SET LOCAL') ? Promise.resolve({ rows: [] }) : select()),
    }) as unknown as PostgresRouter

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
        const service = new OrganizationMembersService(routerFor(query), () => now)

        await expect(service.getBlockedRecipients(1, ['member@example.com'])).rejects.toThrow('expired')
        expect(query).toHaveBeenCalledTimes(2)
    })

    it('fails closed when the fresh lookup outlasts its one-minute decision', async () => {
        let now = 0
        const query = jest.fn(() => {
            now += 60_000
            return Promise.resolve({ rows: [memberRow('member@example.com')] })
        })
        const service = new OrganizationMembersService(routerFor(query), () => now)

        await expect(service.getBlockedRecipients(1, ['member@example.com'], { fresh: true })).rejects.toThrow(
            'expired'
        )
        expect(query).toHaveBeenCalledTimes(1)
    })

    it('shares one member lookup across sends and reloads it after a minute', async () => {
        let now = 0
        let member = 'member@example.com'
        const query = jest.fn(() => Promise.resolve({ rows: [memberRow(member)] }))
        const service = new OrganizationMembersService(routerFor(query), () => now)

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

    it('reloads members for a fresh check inside the minute', async () => {
        let member = 'member@example.com'
        const query = jest.fn(() => Promise.resolve({ rows: [memberRow(member)] }))
        const service = new OrganizationMembersService(routerFor(query), () => 0)

        expect(await service.getBlockedRecipients(1, ['member@example.com'])).toEqual([])
        member = 'new-member@example.com'

        expect(await service.getBlockedRecipients(1, ['member@example.com'], { fresh: true })).toEqual([
            { address: 'member@example.com', unverifiedMember: false },
        ])
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
        const earlierCheck = service.getBlockedRecipients(1, ['member@example.com'])
        while (query.mock.calls.length === 0) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        const freshCheck = service.getBlockedRecipients(1, ['member@example.com'], { fresh: true })
        finishEarlierLookup({ rows: [memberRow('member@example.com')] })

        expect(await earlierCheck).toEqual([])
        expect(await freshCheck).toEqual([{ address: 'member@example.com', unverifiedMember: false }])
        expect(query).toHaveBeenCalledTimes(2)
    })
})
