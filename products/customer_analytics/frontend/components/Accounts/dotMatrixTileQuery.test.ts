import posthog from 'posthog-js'

import { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { DotMatrixTileSource } from '../ProductActivity/dotMatrixTileConfig'
import { queryDotMatrixSource } from './dotMatrixTileQuery'

const sources: DotMatrixTileSource[] = [
    { kind: 'usage_metrics' },
    { kind: 'product_usage' },
    { kind: 'hogql', query: "SELECT 'person@example.com'", mapping: { row: 'account', column: 'period' } },
]

describe('queryDotMatrixSource telemetry', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each(sources.flatMap((source) => [false, true].map((fails) => ({ source, fails }))))(
        'omits query contents for $source.kind when fails=$fails',
        async ({ source, fails }) => {
            let submittedQuery: Record<string, unknown> | undefined
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        submittedQuery = ((await request.json()) as { query: Record<string, unknown> }).query
                        return fails
                            ? [400, { detail: 'Invalid query' }]
                            : [200, { results: [], clickhouse: "SELECT 'person@example.com'" }]
                    },
                },
            })
            const capture = jest.spyOn(posthog, 'capture')
            capture.mockClear()
            const result = queryDotMatrixSource(
                source,
                { accountId: 'test-account-id', externalId: 'test-account-key', groupTypeIndex: 0, weeks: 8 },
                new AbortController().signal,
                'test-query-id'
            )
            if (fails) {
                await expect(result).rejects.toThrow(ApiError)
            } else {
                await result
            }
            if (source.kind === 'hogql') {
                expect(submittedQuery).toMatchObject({ kind: NodeKind.HogQLQuery, query: source.query })
            }
            const events = capture.mock.calls.filter(
                ([event]) => event === (fails ? 'query failed' : 'query completed')
            )
            expect(events).toHaveLength(1)
            expect(events[0][1]?.query).toEqual({ kind: submittedQuery?.kind })
            expect(events[0][1]).not.toHaveProperty('clickhouse_sql')
            expect(JSON.stringify(events[0][1])).not.toMatch(/person@example\.com|test-account-id|test-account-key/)
        }
    )
})
