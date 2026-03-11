import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DatabaseTablePreview } from './DatabaseTablePreview'
import { TablePreviewExpressionColumn } from './types'

type QueryBody = {
    query?: {
        query?: string
    }
}

const eventsTable = {
    name: 'events',
    fields: {
        event: { name: 'event', type: 'String' },
        value: { name: 'value', type: 'Int64' },
    },
}

const personsTable = {
    name: 'persons',
    fields: {
        name: { name: 'name', type: 'String' },
        value: { name: 'value', type: 'Int64' },
    },
}

function queryStringFromRequestBody(reqBody: unknown): string {
    const body = typeof reqBody === 'string' ? (JSON.parse(reqBody) as QueryBody) : ((reqBody || {}) as QueryBody)

    return body.query?.query || ''
}

describe('DatabaseTablePreview', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows empty message when there is no table', async () => {
        let queryCount = 0

        useMocks({
            post: {
                '/api/environments/:team/query': () => {
                    queryCount += 1
                    return [200, { columns: [], results: [] }]
                },
            },
        })

        render(
            <Provider>
                <DatabaseTablePreview table={undefined} emptyMessage="No table selected" />
            </Provider>
        )

        expect(screen.getByText('No table selected')).toBeInTheDocument()
        await waitFor(() => expect(queryCount).toBe(0))
    })

    it.each([
        {
            description: 'table change',
            initialProps: {
                table: eventsTable,
                whereClause: "event = '$pageview'",
                limit: 10,
                expressionColumns: undefined,
            },
            updatedProps: {
                table: personsTable,
                whereClause: "event = '$pageview'",
                limit: 10,
                expressionColumns: undefined,
            },
            expectedQueryContains: 'FROM persons',
        },
        {
            description: 'where clause change',
            initialProps: {
                table: eventsTable,
                whereClause: "event = '$pageview'",
                limit: 10,
                expressionColumns: undefined,
            },
            updatedProps: {
                table: eventsTable,
                whereClause: "event = '$autocapture'",
                limit: 10,
                expressionColumns: undefined,
            },
            expectedQueryContains: "WHERE event = '$autocapture'",
        },
        {
            description: 'limit change',
            initialProps: {
                table: eventsTable,
                whereClause: "event = '$pageview'",
                limit: 10,
                expressionColumns: undefined,
            },
            updatedProps: {
                table: eventsTable,
                whereClause: "event = '$pageview'",
                limit: 5,
                expressionColumns: undefined,
            },
            expectedQueryContains: 'LIMIT 5',
        },
        {
            description: 'expression column change',
            initialProps: {
                table: eventsTable,
                whereClause: "event = '$pageview'",
                limit: 10,
                expressionColumns: undefined,
            },
            updatedProps: {
                table: eventsTable,
                whereClause: "event = '$pageview'",
                limit: 10,
                expressionColumns: [
                    {
                        key: 'normalized_event',
                        expression: 'lower(event)',
                        label: 'Normalized event',
                        type: 'SQL expression',
                    } satisfies TablePreviewExpressionColumn,
                ],
            },
            expectedQueryContains: 'lower(event)',
        },
    ])(
        'refetches and shows updated preview rows on $description',
        async ({ initialProps, updatedProps, expectedQueryContains }) => {
            const executedQueries: string[] = []
            let responseIndex = 0

            useMocks({
                post: {
                    '/api/environments/:team/query': (req) => {
                        const queryString = queryStringFromRequestBody(req.body)
                        executedQueries.push(queryString)

                        const label = responseIndex === 0 ? 'first result' : 'second result'
                        const columns = queryString.includes('FROM persons') ? ['name', 'value'] : ['event', 'value']
                        const response = { columns, results: [[label, responseIndex + 1]] }

                        responseIndex += 1
                        return [200, response]
                    },
                },
            })

            const { rerender } = render(
                <Provider>
                    <DatabaseTablePreview
                        table={initialProps.table as any}
                        whereClause={initialProps.whereClause}
                        limit={initialProps.limit}
                        expressionColumns={initialProps.expressionColumns}
                        emptyMessage="No table selected"
                    />
                </Provider>
            )

            expect(await screen.findByText('first result')).toBeInTheDocument()

            rerender(
                <Provider>
                    <DatabaseTablePreview
                        table={updatedProps.table as any}
                        whereClause={updatedProps.whereClause}
                        limit={updatedProps.limit}
                        expressionColumns={updatedProps.expressionColumns}
                        emptyMessage="No table selected"
                    />
                </Provider>
            )

            expect(await screen.findByText('second result')).toBeInTheDocument()
            expect(screen.queryByText('first result')).not.toBeInTheDocument()
            expect(executedQueries).toHaveLength(2)
            expect(executedQueries[1]).toContain(expectedQueryContains)
        }
    )

    it('renders expression-backed preview columns', async () => {
        const executedQueries: string[] = []

        useMocks({
            post: {
                '/api/environments/:team/query': (req) => {
                    const queryString = queryStringFromRequestBody(req.body)
                    executedQueries.push(queryString)

                    return [
                        200,
                        {
                            columns: ['event', 'value', 'normalized_event'],
                            results: [['$PageView', 1, '$pageview']],
                        },
                    ]
                },
            },
        })

        render(
            <Provider>
                <DatabaseTablePreview
                    table={eventsTable as any}
                    emptyMessage="No table selected"
                    expressionColumns={[
                        {
                            key: 'normalized_event',
                            expression: 'lower(event)',
                            label: 'Normalized event',
                            type: 'SQL expression',
                        },
                    ]}
                />
            </Provider>
        )

        expect(await screen.findByText('Normalized event')).toBeInTheDocument()
        expect(await screen.findByText('$pageview')).toBeInTheDocument()
        expect(executedQueries).toHaveLength(1)
        expect(executedQueries[0]).toContain('lower(event)')
        expect(executedQueries[0]).toContain('normalized_event')
    })
})
