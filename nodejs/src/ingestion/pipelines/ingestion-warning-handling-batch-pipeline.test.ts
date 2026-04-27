import { Message } from 'node-rdkafka'

import { createMockIngestionOutputs } from '../../../tests/helpers/mock-ingestion-outputs'
import { Team } from '../../types'
import * as ingestionWarnings from '../common/ingestion-warnings'
import { IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createContext, createNewBatchPipeline, createOkContext } from './helpers'
import { IngestionWarningHandlingBatchPipeline } from './ingestion-warning-handling-batch-pipeline'
import { ok } from './results'

jest.mock('../common/ingestion-warnings')

function createTestMessage(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('test'),
        topic: 'test',
        partition: 0,
        offset: 1,
        key: Buffer.from('key1'),
        size: 4,
        timestamp: Date.now(),
        headers: [],
        ...overrides,
    }
}

function createTestTeam(overrides: Partial<Team> = {}): Team {
    return {
        id: 1,
        uuid: 'test-team-uuid',
        organization_id: 'test-org-id',
        name: 'Test Team',
        api_token: 'test-token',
        secret_api_token: null,
        anonymize_ips: false,
        session_recording_opt_in: false,
        person_processing_opt_out: null,
        heatmaps_opt_in: null,
        ingested_event: true,
        person_display_name_properties: null,
        test_account_filters: null,
        cookieless_server_hash_mode: null,
        timezone: 'UTC',
        available_features: [],
        drop_events_older_than_seconds: null,
        extra_settings: null,
        project_id: 1 as any,
        ...overrides,
    }
}

describe('IngestionWarningHandlingBatchPipeline', () => {
    let mockOutputs: jest.Mocked<IngestionOutputs<IngestionWarningsOutput>>
    let mockEmitIngestionWarning: jest.MockedFunction<typeof ingestionWarnings.emitIngestionWarning>

    beforeEach(() => {
        mockOutputs = createMockIngestionOutputs<IngestionWarningsOutput>()
        mockEmitIngestionWarning = jest.fn().mockResolvedValue(true)
        ;(ingestionWarnings.emitIngestionWarning as any) = mockEmitIngestionWarning
    })

    describe('basic functionality', () => {
        it('should pass through items without warnings unchanged', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('test2'), offset: 2 }),
            ]

            const team = createTestTeam()
            const batch = [
                createOkContext(
                    { message: messages[0], team },
                    {
                        message: messages[0],
                        team,
                    }
                ),
                createOkContext(
                    { message: messages[1], team },
                    {
                        message: messages[1],
                        team,
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(2)
            expect(results![0]).toEqual(
                createOkContext(
                    { message: messages[0], team },
                    {
                        message: messages[0],
                        team,
                    }
                )
            )
            expect(results![1]).toEqual(
                createOkContext(
                    { message: messages[1], team },
                    {
                        message: messages[1],
                        team,
                    }
                )
            )
            expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
        })

        it('should handle empty batch', async () => {
            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed([])
            const results = await pipeline.next()

            expect(results).toEqual(null)
            expect(mockEmitIngestionWarning).not.toHaveBeenCalled()
        })
    })

    describe('warning handling', () => {
        it('should convert warnings to side effects and clear warnings', async () => {
            const message = createTestMessage()
            const team = createTestTeam()

            const batch = [
                createOkContext(
                    { message, team },
                    {
                        message,
                        team,
                        warnings: [
                            { type: 'test_warning', details: { field: 'value' } },
                            { type: 'another_warning', details: { error: 'something' } },
                        ],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.warnings).toEqual([])
            expect(results![0].context.sideEffects).toHaveLength(2)

            expect(mockEmitIngestionWarning).toHaveBeenCalledTimes(2)
            expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
                mockOutputs,
                team.id,
                'test_warning',
                { field: 'value' },
                { key: undefined, alwaysSend: undefined }
            )
            expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
                mockOutputs,
                team.id,
                'another_warning',
                { error: 'something' },
                { key: undefined, alwaysSend: undefined }
            )
        })

        it('should handle warning with alwaysSend flag', async () => {
            const message = createTestMessage()
            const team = createTestTeam()

            const batch = [
                createOkContext(
                    { message, team },
                    {
                        message,
                        team,
                        warnings: [{ type: 'critical_warning', details: { urgent: true }, alwaysSend: true }],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
                mockOutputs,
                team.id,
                'critical_warning',
                { urgent: true },
                { key: undefined, alwaysSend: true }
            )
            expect(results![0].context.warnings).toEqual([])
        })

        it('should preserve existing side effects while adding warning side effects', async () => {
            const message = createTestMessage()
            const team = createTestTeam()

            const existingSideEffect1 = Promise.resolve('existing-1')
            const existingSideEffect2 = Promise.resolve('existing-2')

            const batch = [
                createOkContext(
                    { message, team },
                    {
                        message,
                        team,
                        sideEffects: [existingSideEffect1, existingSideEffect2],
                        warnings: [{ type: 'test_warning', details: { test: true } }],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(1)
            expect(results![0].context.sideEffects).toHaveLength(3)
            expect(results![0].context.sideEffects[0]).toBe(existingSideEffect1)
            expect(results![0].context.sideEffects[1]).toBe(existingSideEffect2)
            expect(results![0].context.warnings).toEqual([])
        })
    })

    describe('batch processing', () => {
        it('should handle mix of items with and without warnings', async () => {
            const messages: Message[] = [
                createTestMessage({ offset: 1 }),
                createTestMessage({ offset: 2 }),
                createTestMessage({ offset: 3 }),
            ]
            const team = createTestTeam()

            const batch = [
                createOkContext(
                    { message: messages[0], team },
                    {
                        message: messages[0],
                        team,
                        warnings: [{ type: 'warning_1', details: { idx: 1 } }],
                    }
                ),
                createOkContext(
                    { message: messages[1], team },
                    {
                        message: messages[1],
                        team,
                        warnings: [],
                    }
                ),
                createOkContext(
                    { message: messages[2], team },
                    {
                        message: messages[2],
                        team,
                        warnings: [
                            { type: 'warning_3a', details: { idx: 3 } },
                            { type: 'warning_3b', details: { idx: 3, extra: true } },
                        ],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toHaveLength(3)
            expect(results![0].context.warnings).toEqual([])
            expect(results![0].context.sideEffects).toHaveLength(1)
            expect(results![1].context.warnings).toEqual([])
            expect(results![1].context.sideEffects).toHaveLength(0)
            expect(results![2].context.warnings).toEqual([])
            expect(results![2].context.sideEffects).toHaveLength(2)

            expect(mockEmitIngestionWarning).toHaveBeenCalledTimes(3)
        })

        it('should handle multiple items with different teams', async () => {
            const messages: Message[] = [createTestMessage({ offset: 1 }), createTestMessage({ offset: 2 })]
            const team1 = createTestTeam({ id: 1 })
            const team2 = createTestTeam({ id: 2 })

            const batch = [
                createOkContext(
                    { message: messages[0], team: team1 },
                    {
                        message: messages[0],
                        team: team1,
                        warnings: [{ type: 'warning_team1', details: { team: 1 } }],
                    }
                ),
                createOkContext(
                    { message: messages[1], team: team2 },
                    {
                        message: messages[1],
                        team: team2,
                        warnings: [{ type: 'warning_team2', details: { team: 2 } }],
                    }
                ),
            ]

            const rootPipeline = createNewBatchPipeline<{ message: Message; team: Team }, { team: Team }>().build()
            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, rootPipeline)

            pipeline.feed(batch)
            await pipeline.next()

            expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
                mockOutputs,
                team1.id,
                'warning_team1',
                { team: 1 },
                { key: undefined, alwaysSend: undefined }
            )
            expect(mockEmitIngestionWarning).toHaveBeenCalledWith(
                mockOutputs,
                team2.id,
                'warning_team2',
                { team: 2 },
                { key: undefined, alwaysSend: undefined }
            )
        })
    })

    describe('integration with previous pipeline', () => {
        it('should process results from previous pipeline and handle warnings', async () => {
            const messages: Message[] = [
                createTestMessage({ offset: 1 }),
                createTestMessage({ offset: 2 }),
                createTestMessage({ offset: 3 }),
            ]
            const team = createTestTeam()

            const batch = [
                createOkContext({ message: messages[0], team }, { message: messages[0], team }),
                createOkContext({ message: messages[1], team }, { message: messages[1], team }),
                createOkContext({ message: messages[2], team }, { message: messages[2], team }),
            ]

            const previousPipeline = {
                feed: jest.fn(),
                next: jest.fn().mockResolvedValue([
                    createContext(ok({ message: messages[0], team }), {
                        message: messages[0],
                        team,
                        warnings: [{ type: 'upstream_warning', details: { source: 'previous' } }],
                    }),
                    createContext(ok({ message: messages[1], team }), {
                        message: messages[1],
                        team,
                        warnings: [],
                    }),
                    createContext(ok({ message: messages[2], team }), {
                        message: messages[2],
                        team,
                        warnings: [{ type: 'another_upstream_warning', details: { source: 'previous' } }],
                    }),
                ]),
            }

            const pipeline = new IngestionWarningHandlingBatchPipeline(mockOutputs, previousPipeline as any)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(previousPipeline.feed).toHaveBeenCalledWith(batch)
            expect(previousPipeline.next).toHaveBeenCalled()

            expect(results).toHaveLength(3)
            expect(results![0].context.warnings).toEqual([])
            expect(results![1].context.warnings).toEqual([])
            expect(results![2].context.warnings).toEqual([])

            expect(mockEmitIngestionWarning).toHaveBeenCalledTimes(2)
        })
    })
})
