import { PostgresRouter } from '~/common/utils/db/postgres'

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

    it('fails closed after three seconds when the lookup cannot get a connection', async () => {
        jest.useFakeTimers()
        try {
            const query = jest.fn()
            const stalledPool = {
                transaction: () => new Promise<never>(() => {}),
                query,
            } as unknown as PostgresRouter
            const service = new OrganizationMembersService(stalledPool)

            const check = service.checkRecipients(1, ['member@example.com'], { fresh: true })
            const outcome = expect(check).rejects.toThrow('timed out')
            await jest.advanceTimersByTimeAsync(3_000)

            await outcome
            expect(query).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
        }
    })

    it('keeps at most five lookups open while the pool has no connection, and runs no query for them once it recovers', async () => {
        jest.useFakeTimers()
        try {
            let recovered = false
            const waitingForConnection: (() => void)[] = []
            const query = jest.fn((_tx: unknown, sql: string, _params: unknown, tag: string) =>
                Promise.resolve({
                    rows: sql.startsWith('SET LOCAL') || tag === blockQueryTag ? [] : [memberRow('member@example.com')],
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

            await expect(service.checkRecipients(1, ['member@example.com'], { fresh: true })).resolves.toEqual(allowed)
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
