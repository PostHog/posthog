import { DateTime } from 'luxon'

import { getAsyncFunctionHandler } from '../async-function-registry'
import { AsyncFunctionContext } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, MinimalLogEntry } from '../types'
import './posthog-query'

describe('postHogQuery async function', () => {
    const handler = getAsyncFunctionHandler('postHogQuery')!

    function createMockContext(overrides: Partial<AsyncFunctionContext> = {}): AsyncFunctionContext {
        return {
            invocation: {
                teamId: 1,
            } as any,
            globals: {} as any,
            teamManager: {
                getTeam: jest.fn().mockResolvedValue({ api_token: 'test-token-123' }),
            } as any,
            siteUrl: 'https://us.posthog.com',
            ...overrides,
        }
    }

    function createMockResult(): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> {
        return {
            invocation: {
                queueParameters: null,
            } as any,
            finished: false,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
        }
    }

    it('should be registered', () => {
        expect(handler).toBeDefined()
    })

    describe('execute', () => {
        it('should set up fetch queue parameters for a valid query', async () => {
            const context = createMockContext()
            const result = createMockResult()

            await handler.execute([{ query: 'SELECT event FROM events LIMIT 10' }], context, result)

            expect(result.invocation.queueParameters).toEqual({
                type: 'fetch',
                url: 'https://us.posthog.com/api/environments/1/query/',
                method: 'POST',
                body: JSON.stringify({ query: { kind: 'HogQLQuery', query: 'SELECT event FROM events LIMIT 10' } }),
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: 'Bearer test-token-123',
                },
            })
        })

        it('should throw when query is missing', async () => {
            const context = createMockContext()
            const result = createMockResult()

            await expect(handler.execute([{}], context, result)).rejects.toThrow(
                "[HogFunction] - postHogQuery call missing 'query' property"
            )
        })

        it('should throw when query is not a string', async () => {
            const context = createMockContext()
            const result = createMockResult()

            await expect(handler.execute([{ query: 123 }], context, result)).rejects.toThrow(
                "[HogFunction] - postHogQuery call missing 'query' property"
            )
        })

        it('should throw when args are undefined', async () => {
            const context = createMockContext()
            const result = createMockResult()

            await expect(handler.execute([undefined], context, result)).rejects.toThrow(
                "[HogFunction] - postHogQuery call missing 'query' property"
            )
        })

        it('should throw when team is not found', async () => {
            const context = createMockContext({
                teamManager: {
                    getTeam: jest.fn().mockResolvedValue(null),
                } as any,
            })
            const result = createMockResult()

            await expect(handler.execute([{ query: 'SELECT 1' }], context, result)).rejects.toThrow('Team 1 not found')
        })

        it('should use the correct team ID in the URL', async () => {
            const context = createMockContext({
                invocation: { teamId: 42 } as any,
            })
            const result = createMockResult()

            await handler.execute([{ query: 'SELECT 1' }], context, result)

            expect((result.invocation.queueParameters as any).url).toBe(
                'https://us.posthog.com/api/environments/42/query/'
            )
        })
    })

    describe('mock', () => {
        it('should return mock query results', () => {
            const logs: MinimalLogEntry[] = []
            const result = handler.mock([{ query: 'SELECT event, count() FROM events GROUP BY event' }], logs)

            expect(result).toEqual({
                status: 200,
                body: {
                    columns: ['event', 'count'],
                    results: [
                        ['pageview', 1000],
                        ['$autocapture', 500],
                        ['$identify', 250],
                    ],
                    hasMore: false,
                    hogql: 'SELECT event, count() FROM events GROUP BY event',
                },
            })
        })

        it('should add log entries', () => {
            const logs: MinimalLogEntry[] = []
            handler.mock([{ query: 'SELECT 1' }], logs)

            expect(logs).toHaveLength(2)
            expect(logs[0].level).toBe('info')
            expect(logs[0].message).toBe("Async function 'postHogQuery' was mocked with arguments:")
            expect(logs[1].level).toBe('info')
            expect(logs[1].message).toContain('postHogQuery(')
            expect(logs[1].message).toContain('SELECT 1')
        })

        it('should handle missing query in mock gracefully', () => {
            const logs: MinimalLogEntry[] = []
            const result = handler.mock([{}], logs)

            expect(result.body.hogql).toBe('')
        })
    })
})
