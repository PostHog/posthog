import { cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'
import { autocapturePropertiesForElement } from 'posthog-js/lib/src/autocapture'

import { dataColorVars, FALLBACK_DATA_COLOR_THEME } from 'lib/colors'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccountSqlQueryTile } from './AccountSqlQueryTile'

describe('AccountSqlQueryTile', () => {
    beforeEach(() => {
        dataColorVars.forEach((variable, index) => {
            document.body.style.setProperty(`--${variable}`, FALLBACK_DATA_COLOR_THEME[`preset-${index + 1}`])
        })
    })

    afterEach(() => {
        cleanup()
        dataColorVars.forEach((variable) => document.body.style.removeProperty(`--${variable}`))
        jest.restoreAllMocks()
    })

    it.each([
        { outcome: 'success', visualization: undefined },
        { outcome: 'failure', visualization: undefined },
        { outcome: 'empty', visualization: undefined },
        { outcome: 'empty', visualization: { display: 'ActionsTable' } },
    ])('keeps telemetry private on $outcome with visualization $visualization', async ({ outcome, visualization }) => {
        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture')
        const captureException = jest.spyOn(posthog, 'captureException')
        const requests: unknown[] = []
        const query = 'select name from example_engagements where org_id = {account_external_id}'
        const connectionId = '11111111-1111-4111-8111-111111111111'
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    requests.push(body.query)
                    if (outcome === 'failure') {
                        return [400, { detail: 'Example query failed' }]
                    }
                    return {
                        results: outcome === 'empty' ? [] : [['Example result']],
                        columns: ['name'],
                        types: ['String'],
                        clickhouse: 'SELECT name FROM example_engagements',
                    }
                },
            },
        })
        capture.mockClear()

        render(
            <AccountSqlQueryTile
                accountId="example-account"
                externalId="example-org"
                initialConfig={{ query, connectionId, ...(visualization ? { visualization } : {}) }}
            />
        )

        expect(
            await screen.findByText(
                outcome === 'empty'
                    ? /There are no matching (events|rows) for this query/
                    : outcome === 'success'
                      ? 'Example result'
                      : "We couldn't run this query"
            )
        ).not.toBeNull()
        expect(requests).toEqual([
            expect.objectContaining({ query, connectionId, values: { account_external_id: 'example-org' } }),
        ])
        expect(capture.mock.calls.some(([event]) => event === 'insight empty state shown')).toBe(outcome === 'empty')
        expect(capture.mock.calls.filter(([event]) => event === 'query completed' || event === 'query failed')).toEqual(
            []
        )
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example_engagements')
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example-org')
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example-account')
        expect(JSON.stringify(capture.mock.calls)).not.toContain(connectionId)
        expect(captureException).not.toHaveBeenCalled()
    })

    it.each([undefined, { display: 'ActionsTable' }])(
        'renders result values as text with visualization %j',
        async (visualization) => {
            initKeaTests()
            const value = [
                '__hx_tag',
                '__hx_obj',
                '__hx_tag',
                'a',
                'href',
                'https://example.com/details',
                'children',
                'Details',
            ]
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': () => ({
                        results: [[value]],
                        columns: ['details'],
                        types: ['String'],
                    }),
                },
            })
            const { container } = render(
                <AccountSqlQueryTile
                    accountId="example-account"
                    externalId="example-org"
                    initialConfig={{
                        query: 'select details from example_engagements where org_id = {account_external_id}',
                        ...(visualization ? { visualization } : {}),
                    }}
                />
            )
            const cell = await screen.findByText(JSON.stringify(value))
            const result = autocapturePropertiesForElement(cell, {
                e: new Event('copy', { bubbles: true }),
                maskAllElementAttributes: false,
                maskAllText: false,
                elementsChainAsString: false,
                disableCaptureUrlHashes: false,
            })
            expect(result.explicitNoCapture).toBe(true)
            expect(result.props).toEqual({})
            expect(container.querySelector('a[href="https://example.com/details"]')).toBeNull()
        }
    )
})
