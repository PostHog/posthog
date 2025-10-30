import * as grpc from '@grpc/grpc-js'
import { Client, Connection } from '@temporalio/client'

import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { TemporalService } from './temporal.service'

jest.mock('@temporalio/client')
jest.mock('@grpc/grpc-js')
jest.mock('tls')

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

        // Mock tls.createSecureContext
        const tls = require('tls')
        tls.createSecureContext = jest.fn().mockReturnValue({})

        // Mock grpc.credentials.createFromSecureContext
        const mockCredentials = {}
        ;(grpc.credentials as any) = {
            createFromSecureContext: jest.fn().mockReturnValue(mockCredentials),
        }
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
            await service.startEvaluationRunWorkflow('test', 'test')

            expect(Connection.connect).toHaveBeenCalledWith({
                address: 'localhost:7233',
                tls: false,
            })
        })

        it('handles TLS config when certificates provided', async () => {
            hub.TEMPORAL_CLIENT_ROOT_CA = 'root-ca-cert'
            hub.TEMPORAL_CLIENT_CERT = 'client-cert'
            hub.TEMPORAL_CLIENT_KEY = 'client-key'

            const tls = require('tls')
            const mockSecureContext = {}
            tls.createSecureContext = jest.fn().mockReturnValue(mockSecureContext)

            const mockCredentials = {}
            ;(grpc.credentials as any) = {
                createFromSecureContext: jest.fn().mockReturnValue(mockCredentials),
            }

            const newService = new TemporalService(hub)
            await newService.startEvaluationRunWorkflow('test', 'test')

            // Verify SecureContext was created with allowPartialTrustChain
            expect(tls.createSecureContext).toHaveBeenCalledWith({
                ca: expect.any(Buffer),
                cert: expect.any(Buffer),
                key: expect.any(Buffer),
                allowPartialTrustChain: true,
            })

            // Verify gRPC credentials were created from SecureContext
            expect(grpc.credentials.createFromSecureContext).toHaveBeenCalledWith(mockSecureContext)

            // Verify Connection.connect was called with credentials
            expect(Connection.connect).toHaveBeenCalledWith({
                address: 'localhost:7233',
                credentials: mockCredentials,
            })
        })

        it('disconnects client properly', async () => {
            await service.startEvaluationRunWorkflow('test', 'test')
            await service.disconnect()

            expect(mockConnection.close).toHaveBeenCalled()
        })
    })

    describe('workflow triggering', () => {
        it('starts evaluation run workflow with correct parameters', async () => {
            await service.startEvaluationRunWorkflow('eval-123', 'event-456')

            expect(mockClient.workflow.start).toHaveBeenCalledWith('run-evaluation', {
                taskQueue: 'general-purpose-task-queue',
                workflowId: 'eval-123-event-456-ingestion',
                workflowIdConflictPolicy: 'USE_EXISTING',
                args: [
                    {
                        evaluation_id: 'eval-123',
                        target_event_id: 'event-456',
                    },
                ],
            })
        })

        it('generates deterministic workflow IDs', async () => {
            await service.startEvaluationRunWorkflow('eval-123', 'event-456')
            await service.startEvaluationRunWorkflow('eval-123', 'event-456')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).toEqual(workflowId2)
            expect(workflowId1).toBe('eval-123-event-456-ingestion')
        })

        it('generates different workflow IDs for different events', async () => {
            await service.startEvaluationRunWorkflow('eval-123', 'event-1')
            await service.startEvaluationRunWorkflow('eval-123', 'event-2')

            const calls = (mockClient.workflow.start as jest.Mock).mock.calls
            const workflowId1 = calls[0][1].workflowId
            const workflowId2 = calls[1][1].workflowId

            expect(workflowId1).not.toEqual(workflowId2)
            expect(workflowId1).toBe('eval-123-event-1-ingestion')
            expect(workflowId2).toBe('eval-123-event-2-ingestion')
        })

        it('returns workflow handle on success', async () => {
            const handle = await service.startEvaluationRunWorkflow('eval-123', 'event-456')

            expect(handle).toBeDefined()
            expect(handle).toBe(mockWorkflowHandle)
        })

        it('throws on workflow start failure', async () => {
            ;(mockClient.workflow.start as jest.Mock).mockRejectedValue(new Error('Temporal unavailable'))

            await expect(service.startEvaluationRunWorkflow('eval-123', 'event-456')).rejects.toThrow(
                'Temporal unavailable'
            )
        })
    })
})
