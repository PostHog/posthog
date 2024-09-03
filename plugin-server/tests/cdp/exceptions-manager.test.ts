import { ExceptionsManager } from '../../src/cdp/exceptions-manager'
import { Hub } from '../../src/types'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './fixtures'

describe('Exceptions Manager', () => {
    jest.setTimeout(1000)
    let exceptionsManager: ExceptionsManager

    let mockGroups: { team_id: number; status: string; fingerprint: string[]; merged_fingerprints: string[][] }[] = []

    const mockHub = {
        postgres: {
            query: jest.fn(),
        },
    }

    beforeEach(() => {
        exceptionsManager = new ExceptionsManager(mockHub as unknown as Hub)
    })

    describe('unit tests', () => {
        beforeEach(() => {
            mockHub.postgres.query.mockImplementation((_, query): Promise<any> => {
                if (query.includes('posthog_errortrackinggroup')) {
                    return Promise.resolve({ rows: mockGroups })
                }
                return Promise.resolve({
                    rows: [],
                })
            })

            mockGroups = [
                { team_id: 1, status: 'active', fingerprint: ['SyntaxError'], merged_fingerprints: [['custom_fp-1']] },
                { team_id: 2, status: 'active', fingerprint: ['ApiError'], merged_fingerprints: [['custom_fp-1']] },
                { team_id: 1, status: 'archived', fingerprint: ['TypeError'], merged_fingerprints: [['custom_fp-2']] },
                { team_id: 1, status: 'active', fingerprint: ['Error'], merged_fingerprints: [] },
                { team_id: 1, status: 'resolved', fingerprint: ['ApiError'], merged_fingerprints: [] },
                { team_id: 1, status: 'pending_release', fingerprint: ['ObjectError'], merged_fingerprints: [] },
            ]
        })

        it('enriches exceptions', async () => {
            const items = [
                // Should enrich a simple exception
                createHogExecutionGlobals({
                    event: {
                        name: '$exception',
                        properties: {
                            $exception_fingerprint: ['custom_fp-1'],
                        },
                    } as any,
                    project: { id: 1 } as any,
                }),
                // Should enrich archived fingerprints
                createHogExecutionGlobals({
                    event: {
                        name: '$exception',
                        properties: {
                            $exception_fingerprint: ['custom_fp-2'],
                        },
                    } as any,
                    project: { id: 1 } as any,
                }),
                // Should get the right fingerprint for its team
                createHogExecutionGlobals({
                    event: {
                        name: '$exception',
                        properties: {
                            $exception_fingerprint: ['custom_fp-1'],
                        },
                    } as any,
                    project: { id: 2 } as any,
                }),
            ]
            await exceptionsManager.enrichExceptions(items)

            expect(items[0].event).toMatchInlineSnapshot(`
                Object {
                  "distinct_id": "distinct_id",
                  "name": "$exception",
                  "properties": Object {
                    "$exception_fingerprint": Array [
                      "SyntaxError",
                    ],
                  },
                  "timestamp": "2024-09-03T10:39:31.422Z",
                  "url": "http://localhost:8000/events/1",
                  "uuid": "uuid",
                }
            `)
            expect(items[1].event).toMatchInlineSnapshot(`
                Object {
                  "distinct_id": "distinct_id",
                  "name": "$exception",
                  "properties": Object {
                    "$exception_fingerprint": Array [
                      "TypeError",
                    ],
                  },
                  "timestamp": "2024-09-03T10:39:31.422Z",
                  "url": "http://localhost:8000/events/1",
                  "uuid": "uuid",
                }
            `)
            expect(items[2].event).toMatchInlineSnapshot(`
                Object {
                  "distinct_id": "distinct_id",
                  "name": "$exception",
                  "properties": Object {
                    "$exception_fingerprint": Array [
                      "ApiError",
                    ],
                  },
                  "timestamp": "2024-09-03T10:39:31.422Z",
                  "url": "http://localhost:8000/events/1",
                  "uuid": "uuid",
                }
            `)
        })

        it('does nothing if no fingerprint mapping found', async () => {
            const globals = createHogExecutionGlobals({
                event: {
                    name: '$exception',
                    properties: {
                        $exception_fingerprint: ['unmapped_fingerprint'],
                    },
                } as any,
                project: { id: 1 } as any,
            })
            await exceptionsManager.enrichExceptions([globals])

            expect(globals.event).toMatchInlineSnapshot(`
                Object {
                  "distinct_id": "distinct_id",
                  "name": "$exception",
                  "properties": Object {
                    "$exception_fingerprint": Array [
                      "unmapped_fingerprint",
                    ],
                  },
                  "timestamp": "2024-09-03T10:39:31.436Z",
                  "url": "http://localhost:8000/events/1",
                  "uuid": "uuid",
                }
            `)
        })

        it('does nothing for non exception events', async () => {
            const globals = createHogExecutionGlobals({
                event: {
                    name: 'custom_event',
                    properties: {
                        $exception_fingerprint: ['custom_fp-1'],
                    },
                } as any,
                project: {
                    id: 1,
                } as any,
            })
            await exceptionsManager.enrichExceptions([globals])

            expect(globals.event).toMatchInlineSnapshot(`
                Object {
                  "distinct_id": "distinct_id",
                  "name": "custom_event",
                  "properties": Object {
                    "$exception_fingerprint": Array [
                      "custom_fp-1",
                    ],
                  },
                  "timestamp": "2024-09-03T10:39:31.436Z",
                  "url": "http://localhost:8000/events/1",
                  "uuid": "uuid",
                }
            `)
        })
    })

    it('cached exception group queries', async () => {
        const globals = [
            createHogExecutionGlobals({
                event: { name: '$exception', properties: { $exception_fingerprint: ['custom_fp-1'] } } as any,
                project: { id: 1 } as any,
            }),
            createHogExecutionGlobals({
                event: { name: '$exception', properties: { $exception_fingerprint: ['custom_fp-2'] } } as any,
                project: { id: 2 } as any,
            }),
        ]
        await exceptionsManager.enrichExceptions(globals)
        expect(mockHub.postgres.query).toHaveBeenCalledTimes(1)
        mockHub.postgres.query.mockClear()

        await exceptionsManager.enrichExceptions(globals)
        expect(mockHub.postgres.query).not.toHaveBeenCalled()
        mockHub.postgres.query.mockClear()

        globals.push(
            createHogExecutionGlobals({
                event: { name: '$exception', properties: { $exception_fingerprint: ['custom_fp-1'] } } as any,
                project: { id: 3 } as any,
            })
        )

        await exceptionsManager.enrichExceptions(globals)
        expect(mockHub.postgres.query).toHaveBeenCalledTimes(1)
    })
})
