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
        hub.TEMPORAL_HOST = 'localhost:7233'
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
            await service.startEvaluationWorkflow('test', 'test')

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
            await newService.startEvaluationWorkflow('test', 'test')

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
            await service.startEvaluationWorkflow('test', 'test')
            await service.disconnect()

            expect(mockConnection.close).toHaveBeenCalled()
        })
    })

    describe('workflow triggering', () => {
        it('starts evaluation workflow with correct parameters', async () => {
            await service.startEvaluationWorkflow('eval-123', 'event-456')

            expect(mockClient.workflow.start).toHaveBeenCalledWith('run-evaluation', {
                taskQueue: 'general-purpose-task-queue',
                workflowId: expect.stringContaining('eval-123'),
                args: [
                    {
                        evaluation_id: 'eval-123',
                        target_event_id: 'event-456',
                    },
                ],
            })
        })

        it('generates unique workflow IDs', async () => {
            await service.startEvaluationWorkflow('eval-123', 'event-1')
            await service.startEvaluationWorkflow('eval-123', 'event-2')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).not.toEqual(workflowId2)
            expect(workflowId1).toContain('eval-123')
            expect(workflowId2).toContain('eval-123')
        })

        it('does not throw on workflow start failure', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(new Error('Temporal unavailable'))

            await expect(service.startEvaluationWorkflow('eval-123', 'event-456')).resolves.not.toThrow()
        })

        it('logs error on workflow start failure', async () => {
            const error = new Error('Connection failed')
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(error)

            const loggerSpy = jest.spyOn(require('../../utils/logger').logger, 'error')

            await service.startEvaluationWorkflow('eval-123', 'event-456')

            expect(loggerSpy).toHaveBeenCalledWith(
                'Failed to start evaluation workflow',
                expect.objectContaining({
                    evaluationId: 'eval-123',
                    targetEventId: 'event-456',
                    error: 'Connection failed',
                })
            )
        })
    })
})
