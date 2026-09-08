import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { upgradeQueryToLatestVersion } from './upgradeQuery'

describe('upgradeQueryToLatestVersion()', () => {
    const staleQuery = { kind: NodeKind.TrendsQuery, series: [], version: 1 } as any
    const upgradedQuery = { kind: NodeKind.TrendsQuery, series: [], version: 4 }
    let statuses: number[]
    let calls: number

    beforeEach(() => {
        calls = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/upgrade': () => {
                    const status = statuses[calls] ?? 200
                    calls += 1
                    return [status, status === 200 ? { query: upgradedQuery } : {}]
                },
            },
        })
        initKeaTests()
    })

    const cases: [string, number[], boolean, number][] = [
        ['upgrades a stale query', [200], true, 1],
        ['retries once after a transient gateway failure', [503, 200], true, 2],
        ['keeps the query when the retry fails too', [503, 503], false, 2],
        ['keeps the query without retrying when access is denied', [403], false, 1],
    ]

    it.each(cases)('%s', async (_name, responseStatuses, expectUpgraded, expectedCalls) => {
        statuses = responseStatuses

        await expect(upgradeQueryToLatestVersion(staleQuery)).resolves.toEqual(expectUpgraded ? upgradedQuery : null)
        expect(calls).toEqual(expectedCalls)
    })

    it('does not call the API for a query already on the latest version', async () => {
        statuses = []
        const query = { kind: NodeKind.TrendsQuery, series: [], version: 4 } as any

        await expect(upgradeQueryToLatestVersion(query)).resolves.toEqual(query)
        expect(calls).toEqual(0)
    })
})
