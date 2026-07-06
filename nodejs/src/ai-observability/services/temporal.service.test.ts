import { Client, Connection, WorkflowExecutionAlreadyStartedError } from '@temporalio/client'

import { EncryptionCodec } from '~/common/temporal/codec'
import { RawKafkaEvent } from '~/types'

import { DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS, TemporalService, workflowSafeTraceId } from './temporal.service'
import type { EvaluationWorkflowRuntime, TemporalServiceConfig } from './temporal.service'

jest.mock('@temporalio/client')

const createMockEvent = (overrides: Partial<RawKafkaEvent> = {}): RawKafkaEvent => {
    return {
        uuid: 'event-456',
        event: '$ai_generation',
        properties: '{}',
        timestamp: '2024-01-01T00:00:00Z',
        team_id: 1,
        distinct_id: 'test-user',
        elements_chain: '',
        created_at: '2024-01-01T00:00:00Z',
        project_id: 1,
        ...overrides,
    } as RawKafkaEvent
}

describe('TemporalService', () => {
    let config: TemporalServiceConfig
    let service: TemporalService
    let mockClient: jest.Mocked<Client>
    let mockConnection: jest.Mocked<Connection>
    let mockWorkflowHandle: any

    beforeEach(() => {
        config = {
            TEMPORAL_CLIENT_ROOT_CA: undefined,
            TEMPORAL_CLIENT_CERT: undefined,
            TEMPORAL_CLIENT_KEY: undefined,
            TEMPORAL_PORT: '7233',
            TEMPORAL_HOST: 'localhost',
            TEMPORAL_NAMESPACE: 'test-namespace',
            TEMPORAL_SECRET_KEY: undefined,
            TEMPORAL_FALLBACK_SECRET_KEYS: '',
        }

        mockWorkflowHandle = {
            workflowId: 'test-workflow-id',
        }

        mockConnection = {
            close: jest.fn().mockResolvedValue(undefined),
        } as any

        mockClient = {
            workflow: {
                start: jest.fn().mockResolvedValue(mockWorkflowHandle),
            },
            connection: mockConnection,
        } as any
        ;(Connection.connect as jest.Mock) = jest.fn().mockResolvedValue(mockConnection)
        ;(Client as unknown as jest.Mock) = jest.fn().mockReturnValue(mockClient)

        service = new TemporalService(config)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('connection management', () => {
        it('creates client with correct config', async () => {
            await service.startEvaluationRunWorkflow('test', createMockEvent({ uuid: 'test-uuid' }), 'llm_judge')

            expect(Connection.connect).toHaveBeenCalledWith({
                address: 'localhost:7233',
                tls: false,
            })
        })

        it('handles TLS config when certificates provided', async () => {
            config.TEMPORAL_CLIENT_ROOT_CA = 'root-ca-cert'
            config.TEMPORAL_CLIENT_CERT = 'client-cert'
            config.TEMPORAL_CLIENT_KEY = 'client-key'

            const newService = new TemporalService(config)
            await newService.startEvaluationRunWorkflow('test', createMockEvent({ uuid: 'test-uuid' }), 'llm_judge')

            expect(Connection.connect).toHaveBeenCalledWith({
                address: 'localhost:7233',
                tls: {
                    serverRootCACertificate: expect.any(Buffer),
                    clientCertPair: {
                        crt: expect.any(Buffer),
                        key: expect.any(Buffer),
                    },
                },
            })
        })

        it('configures an encryption codec when a secret key is set', async () => {
            config.TEMPORAL_SECRET_KEY = 'test-secret-key-for-codec-000000'
            config.TEMPORAL_FALLBACK_SECRET_KEYS = 'fallback-key-one-000000000000000,fallback-key-two-000000000000000'

            const newService = new TemporalService(config)
            await newService.startEvaluationRunWorkflow('test', createMockEvent({ uuid: 'test-uuid' }), 'llm_judge')

            const clientOptions = (Client as unknown as jest.Mock).mock.calls[0][0]
            expect(clientOptions.dataConverter.payloadCodecs).toHaveLength(1)
            expect(clientOptions.dataConverter.payloadCodecs[0]).toBeInstanceOf(EncryptionCodec)
        })

        it('sends payloads unencrypted when no secret key is set', async () => {
            config.TEMPORAL_SECRET_KEY = undefined

            const newService = new TemporalService(config)
            await newService.startEvaluationRunWorkflow('test', createMockEvent({ uuid: 'test-uuid' }), 'llm_judge')

            const clientOptions = (Client as unknown as jest.Mock).mock.calls[0][0]
            expect(clientOptions.dataConverter).toBeUndefined()
        })

        it('disconnects client properly', async () => {
            await service.startEvaluationRunWorkflow('test', createMockEvent({ uuid: 'test-uuid' }), 'llm_judge')
            await service.disconnect()

            expect(mockConnection.close).toHaveBeenCalled()
        })
    })

    describe('workflow triggering', () => {
        it('starts evaluation run workflow with correct parameters', async () => {
            const mockEvent = createMockEvent({ properties: { $ai_input: 'test', $ai_output: 'response' } as any })

            await service.startEvaluationRunWorkflow('eval-123', mockEvent, 'llm_judge')

            expect(mockClient.workflow.start).toHaveBeenCalledWith('run-evaluation', {
                taskQueue: 'llm-analytics-evals-task-queue',
                workflowId: 'llma-llm-eval-eval-123-event-456-ingestion',
                workflowIdConflictPolicy: 'USE_EXISTING',
                workflowIdReusePolicy: 'ALLOW_DUPLICATE_FAILED_ONLY',
                workflowTaskTimeout: '2 minutes',
                args: [
                    {
                        evaluation_id: 'eval-123',
                        event_data: mockEvent,
                    },
                ],
            })
        })

        it('uses sentiment workflow prefix for sentiment evaluations', async () => {
            const mockEvent = createMockEvent()

            await service.startEvaluationRunWorkflow('eval-123', mockEvent, 'sentiment')

            expect(mockClient.workflow.start).toHaveBeenCalledWith(
                'run-evaluation',
                expect.objectContaining({
                    workflowId: 'llma-sentiment-eval-eval-123-event-456-ingestion',
                })
            )
        })

        it('throws when evaluation runtime has no workflow prefix', async () => {
            await expect(
                service.startEvaluationRunWorkflow(
                    'eval-123',
                    createMockEvent(),
                    'unknown' as EvaluationWorkflowRuntime
                )
            ).rejects.toThrow('Unsupported evaluation runtime: unknown')

            expect(mockClient.workflow.start).not.toHaveBeenCalled()
        })

        it('generates deterministic workflow IDs', async () => {
            const mockEvent = createMockEvent()

            await service.startEvaluationRunWorkflow('eval-123', mockEvent, 'llm_judge')
            await service.startEvaluationRunWorkflow('eval-123', mockEvent, 'llm_judge')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).toEqual(workflowId2)
            expect(workflowId1).toBe('llma-llm-eval-eval-123-event-456-ingestion')
        })

        it('generates different workflow IDs for different events', async () => {
            const mockEvent1 = createMockEvent({ uuid: 'event-1' })
            const mockEvent2 = createMockEvent({ uuid: 'event-2' })

            await service.startEvaluationRunWorkflow('eval-123', mockEvent1, 'llm_judge')
            await service.startEvaluationRunWorkflow('eval-123', mockEvent2, 'llm_judge')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).not.toEqual(workflowId2)
            expect(workflowId1).toBe('llma-llm-eval-eval-123-event-1-ingestion')
            expect(workflowId2).toBe('llma-llm-eval-eval-123-event-2-ingestion')
        })

        it('returns workflow handle on success', async () => {
            const handle = await service.startEvaluationRunWorkflow('eval-123', createMockEvent(), 'llm_judge')

            expect(handle).toBe(mockWorkflowHandle)
        })

        it('throws on workflow start failure', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(new Error('Temporal unavailable'))

            await expect(
                service.startEvaluationRunWorkflow('eval-123', createMockEvent(), 'llm_judge')
            ).rejects.toThrow('Temporal unavailable')
        })

        it('starts tagger run workflow with correct parameters', async () => {
            const mockEvent = createMockEvent({ properties: { $ai_input: 'test', $ai_output: 'response' } as any })

            await service.startTaggerRunWorkflow('tagger-123', mockEvent)

            expect(mockClient.workflow.start).toHaveBeenCalledWith('run-tagger', {
                taskQueue: 'llm-analytics-evals-task-queue',
                workflowId: 'llma-tagger-tagger-123-event-456-ingestion',
                workflowIdConflictPolicy: 'USE_EXISTING',
                workflowIdReusePolicy: 'ALLOW_DUPLICATE_FAILED_ONLY',
                workflowTaskTimeout: '2 minutes',
                args: [
                    {
                        tagger_id: 'tagger-123',
                        event_data: mockEvent,
                    },
                ],
            })
        })

        it('generates deterministic tagger workflow IDs', async () => {
            const mockEvent = createMockEvent()

            await service.startTaggerRunWorkflow('tagger-123', mockEvent)
            await service.startTaggerRunWorkflow('tagger-123', mockEvent)

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            expect(calls[0][1].workflowId).toEqual(calls[1][1].workflowId)
            expect(calls[0][1].workflowId).toBe('llma-tagger-tagger-123-event-456-ingestion')
        })

        it('generates different tagger workflow IDs for different events', async () => {
            const mockEvent1 = createMockEvent({ uuid: 'event-1' })
            const mockEvent2 = createMockEvent({ uuid: 'event-2' })

            await service.startTaggerRunWorkflow('tagger-123', mockEvent1)
            await service.startTaggerRunWorkflow('tagger-123', mockEvent2)

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            expect(calls[0][1].workflowId).toBe('llma-tagger-tagger-123-event-1-ingestion')
            expect(calls[1][1].workflowId).toBe('llma-tagger-tagger-123-event-2-ingestion')
        })

        it('tagger and evaluation share the same task queue', async () => {
            await service.startEvaluationRunWorkflow('eval-1', createMockEvent({ uuid: 'e1' }), 'llm_judge')
            await service.startTaggerRunWorkflow('tagger-1', createMockEvent({ uuid: 'e2' }))

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            expect(calls[0][1].taskQueue).toEqual(calls[1][1].taskQueue)
        })

        it('throws on tagger workflow start failure', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(new Error('Temporal unavailable'))

            await expect(service.startTaggerRunWorkflow('tagger-123', createMockEvent())).rejects.toThrow(
                'Temporal unavailable'
            )
        })
    })

    describe('trace evaluation workflows', () => {
        it('starts the trace workflow with slim inputs and the passed aggregation window', async () => {
            const mockEvent = createMockEvent()

            await service.startTraceEvaluationRunWorkflow('eval-123', mockEvent, 'trace-789', 'session-1', 60)

            expect(mockClient.workflow.start).toHaveBeenCalledWith('run-trace-evaluation', {
                taskQueue: 'llm-analytics-evals-task-queue',
                workflowId: 'llma-trace-eval-eval-123-trace-789',
                workflowIdConflictPolicy: 'USE_EXISTING',
                workflowIdReusePolicy: 'ALLOW_DUPLICATE_FAILED_ONLY',
                workflowTaskTimeout: '2 minutes',
                args: [
                    {
                        evaluation_id: 'eval-123',
                        team_id: 1,
                        trace_id: 'trace-789',
                        distinct_id: 'test-user',
                        session_id: 'session-1',
                        window_seconds: 60,
                    },
                ],
            })
        })

        it('produces the same workflow id for every event of the same trace', async () => {
            await service.startTraceEvaluationRunWorkflow(
                'eval-123',
                createMockEvent({ uuid: 'event-1' }),
                'trace-789',
                null,
                DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS
            )
            await service.startTraceEvaluationRunWorkflow(
                'eval-123',
                createMockEvent({ uuid: 'event-2' }),
                'trace-789',
                null,
                DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS
            )

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            expect(calls[0][1].workflowId).toEqual(calls[1][1].workflowId)
            expect(calls[0][1].workflowId).not.toContain('event-1')
        })

        it('returns null when a completed run already exists for the trace', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(
                new WorkflowExecutionAlreadyStartedError('already started', 'wf-id', 'run-trace-evaluation')
            )

            const handle = await service.startTraceEvaluationRunWorkflow(
                'eval-123',
                createMockEvent(),
                'trace-789',
                null,
                DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS
            )

            expect(handle).toBeNull()
        })

        it('rethrows non-dedup start failures', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(new Error('Temporal unavailable'))

            await expect(
                service.startTraceEvaluationRunWorkflow(
                    'eval-123',
                    createMockEvent(),
                    'trace-789',
                    null,
                    DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS
                )
            ).rejects.toThrow('Temporal unavailable')
        })
    })

    describe('workflowSafeTraceId', () => {
        it('keeps short trace ids as-is', () => {
            expect(workflowSafeTraceId('trace-789')).toBe('trace-789')
        })

        it('hashes oversized trace ids deterministically', () => {
            const longTraceId = 'x'.repeat(500)

            const safeId = workflowSafeTraceId(longTraceId)

            expect(safeId).toHaveLength(32)
            expect(safeId).toBe(workflowSafeTraceId(longTraceId))
            expect(safeId).not.toBe(workflowSafeTraceId(`${longTraceId}y`))
        })
    })
})
