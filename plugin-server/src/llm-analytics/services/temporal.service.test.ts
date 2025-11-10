import { Client, Connection } from '@temporalio/client'

import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { TemporalService } from './temporal.service'

jest.mock('@temporalio/client')

describe('TemporalService', () => {
    let hub: Hub
    let service: TemporalService
    let mockClient: jest.Mocked<Client>
    let mockConnection: jest.Mocked<Connection>
    let mockWorkflowHandle: any

    beforeEach(async () => {
        hub = await createHub()
        hub.TEMPORAL_HOST = 'localhost'
        hub.TEMPORAL_PORT = '7233'
        hub.TEMPORAL_NAMESPACE = 'test-namespace'

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

        service = new TemporalService(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('connection management', () => {
        it('creates client with correct config', async () => {
            await service.startEvaluationRunWorkflow('test', 'test', '2024-01-01T00:00:00Z')

            expect(Connection.connect).toHaveBeenCalledWith({
                address: 'localhost:7233',
                tls: false,
            })
        })

        it('handles TLS config when certificates provided', async () => {
            hub.TEMPORAL_CLIENT_ROOT_CA = 'root-ca-cert'
            hub.TEMPORAL_CLIENT_CERT = 'client-cert'
            hub.TEMPORAL_CLIENT_KEY = 'client-key'

            const newService = new TemporalService(hub)
            await newService.startEvaluationRunWorkflow('test', 'test', '2024-01-01T00:00:00Z')

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

        it('disconnects client properly', async () => {
            await service.startEvaluationRunWorkflow('test', 'test', '2024-01-01T00:00:00Z')
            await service.disconnect()

            expect(mockConnection.close).toHaveBeenCalled()
        })
    })

    describe('workflow triggering', () => {
        it('starts evaluation run workflow with correct parameters', async () => {
            await service.startEvaluationRunWorkflow('eval-123', 'event-456', '2024-01-01T00:00:00Z')

            expect(mockClient.workflow.start).toHaveBeenCalledWith('run-evaluation', {
                taskQueue: 'general-purpose-task-queue',
                workflowId: 'eval-123-event-456-ingestion',
                workflowIdConflictPolicy: 'USE_EXISTING',
                args: [
                    {
                        evaluation_id: 'eval-123',
                        target_event_id: 'event-456',
                        timestamp: '2024-01-01T00:00:00Z',
                    },
                ],
            })
        })

        it('generates deterministic workflow IDs', async () => {
            await service.startEvaluationRunWorkflow('eval-123', 'event-456', '2024-01-01T00:00:00Z')
            await service.startEvaluationRunWorkflow('eval-123', 'event-456', '2024-01-01T00:00:00Z')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).toEqual(workflowId2)
            expect(workflowId1).toBe('eval-123-event-456-ingestion')
        })

        it('generates different workflow IDs for different events', async () => {
            await service.startEvaluationRunWorkflow('eval-123', 'event-1', '2024-01-01T00:00:00Z')
            await service.startEvaluationRunWorkflow('eval-123', 'event-2', '2024-01-01T00:00:00Z')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).not.toEqual(workflowId2)
            expect(workflowId1).toBe('eval-123-event-1-ingestion')
            expect(workflowId2).toBe('eval-123-event-2-ingestion')
        })

        it('returns workflow handle on success', async () => {
            const handle = await service.startEvaluationRunWorkflow('eval-123', 'event-456', '2024-01-01T00:00:00Z')

            expect(handle).toBeDefined()
            expect(handle).toBe(mockWorkflowHandle)
        })

        it('throws on workflow start failure', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(new Error('Temporal unavailable'))

            await expect(
                service.startEvaluationRunWorkflow('eval-123', 'event-456', '2024-01-01T00:00:00Z')
            ).rejects.toThrow('Temporal unavailable')
        })
    })
})
