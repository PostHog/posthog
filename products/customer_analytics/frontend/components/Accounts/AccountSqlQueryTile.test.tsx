import { cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccountSqlQueryTile } from './AccountSqlQueryTile'

describe('AccountSqlQueryTile', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each(['success', 'failure'])('keeps execution telemetry private on %s', async (outcome) => {
        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture')
        const captureException = jest.spyOn(posthog, 'captureException')
        const requests: unknown[] = []
        const query = 'select name from example_engagements where org_id = {account_external_id}'
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    requests.push(body.query)
                    if (outcome === 'failure') {
                        return [400, { detail: 'Example query failed' }]
                    }
                    return {
                        results: [['Example result']],
                        columns: ['name'],
                        types: ['String'],
                        clickhouse: 'SELECT name FROM example_engagements',
                    }
                },
            },
        })
        capture.mockClear()

        render(<AccountSqlQueryTile accountId="example-account" externalId="example-org" initialConfig={{ query }} />)

        expect(
            await screen.findByText(outcome === 'success' ? 'Example result' : "We couldn't run this query")
        ).not.toBeNull()
        expect(requests).toEqual([expect.objectContaining({ query, values: { account_external_id: 'example-org' } })])
        expect(capture.mock.calls.filter(([event]) => event === 'query completed' || event === 'query failed')).toEqual(
            []
        )
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example_engagements')
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example-org')
        expect(captureException).not.toHaveBeenCalled()
    })
})
