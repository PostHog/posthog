import { CyclotronJobInvocationResult } from '../types'
import { CapturedEventsService } from './captured-events/captured-events.service'
import { InvocationResultsService } from './invocation-results.service'
import { MessageAssetsService } from './messaging/message-assets.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from './monitoring/hog-invocation-results.service'
import { WarehouseWebhookStatusService } from './warehouse/warehouse-webhook-status.service'
import { WarehouseWebhooksService } from './warehouse/warehouse-webhooks.service'

describe('InvocationResultsService', () => {
    let monitoringService: jest.Mocked<HogFunctionMonitoringService>
    let invocationResultsRowsService: jest.Mocked<HogInvocationResultsService>
    let warehouseWebhooksService: jest.Mocked<WarehouseWebhooksService>
    let warehouseWebhookStatusService: jest.Mocked<WarehouseWebhookStatusService>
    let capturedEventsService: jest.Mocked<CapturedEventsService>
    let messageAssetsService: jest.Mocked<MessageAssetsService>
    let service: InvocationResultsService

    const results = [
        { capturedPostHogEvents: [], warehouseWebhookPayloads: [] },
        { capturedPostHogEvents: [], warehouseWebhookPayloads: [] },
    ] as unknown as CyclotronJobInvocationResult[]

    beforeEach(() => {
        monitoringService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogFunctionMonitoringService>

        invocationResultsRowsService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogInvocationResultsService>

        warehouseWebhooksService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<WarehouseWebhooksService>

        warehouseWebhookStatusService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<WarehouseWebhookStatusService>

        capturedEventsService = {
            queueInvocationResults: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CapturedEventsService>

        messageAssetsService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<MessageAssetsService>

        service = new InvocationResultsService(
            monitoringService,
            invocationResultsRowsService,
            warehouseWebhooksService,
            warehouseWebhookStatusService,
            capturedEventsService,
            messageAssetsService
        )
    })

    describe('queueInvocationResults', () => {
        it('fans the same results out to all sub-services', async () => {
            await service.queueInvocationResults(results)

            expect(monitoringService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(monitoringService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(invocationResultsRowsService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(invocationResultsRowsService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(warehouseWebhooksService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(warehouseWebhooksService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(warehouseWebhookStatusService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(warehouseWebhookStatusService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(capturedEventsService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(capturedEventsService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(messageAssetsService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(messageAssetsService.queueInvocationResults).toHaveBeenCalledWith(results)
        })

        it('awaits the captured-events service (which is async)', async () => {
            let resolveCaptured: () => void = () => {}
            capturedEventsService.queueInvocationResults.mockReturnValueOnce(
                new Promise((resolve) => {
                    resolveCaptured = resolve
                })
            )

            const queuePromise = service.queueInvocationResults(results)
            // Give the microtask queue a chance to run the synchronous calls
            await new Promise((r) => setImmediate(r))

            expect(monitoringService.queueInvocationResults).toHaveBeenCalled()
            expect(warehouseWebhooksService.queueInvocationResults).toHaveBeenCalled()
            // queueInvocationResults should not yet be resolved because captured is still pending
            let resolved = false
            void queuePromise.then(() => {
                resolved = true
            })
            await new Promise((r) => setImmediate(r))
            expect(resolved).toBe(false)

            resolveCaptured()
            await queuePromise
        })
    })

    describe('flush', () => {
        it('flushes all sub-services', async () => {
            await service.flush()

            expect(monitoringService.flush).toHaveBeenCalledTimes(1)
            expect(invocationResultsRowsService.flush).toHaveBeenCalledTimes(1)
            expect(warehouseWebhooksService.flush).toHaveBeenCalledTimes(1)
            expect(warehouseWebhookStatusService.flush).toHaveBeenCalledTimes(1)
            expect(capturedEventsService.flush).toHaveBeenCalledTimes(1)
            expect(messageAssetsService.flush).toHaveBeenCalledTimes(1)
        })

        it('flushes all in parallel (all start before any finish)', async () => {
            const order: string[] = []
            const trackOrder = (name: string) =>
                jest.fn().mockImplementation(() => {
                    order.push(`${name}:start`)
                    return Promise.resolve().then(() => {
                        order.push(`${name}:end`)
                    })
                })

            monitoringService.flush = trackOrder('monitoring')
            invocationResultsRowsService.flush = trackOrder('invocationResults')
            warehouseWebhooksService.flush = trackOrder('warehouse')
            warehouseWebhookStatusService.flush = trackOrder('warehouseStatus')
            capturedEventsService.flush = trackOrder('captured')

            await service.flush()

            // All should have started before any of them finish — proves Promise.all parallelism.
            const lastStart = Math.max(
                order.indexOf('monitoring:start'),
                order.indexOf('invocationResults:start'),
                order.indexOf('warehouse:start'),
                order.indexOf('warehouseStatus:start'),
                order.indexOf('captured:start')
            )
            const firstEnd = Math.min(
                order.indexOf('monitoring:end'),
                order.indexOf('invocationResults:end'),
                order.indexOf('warehouse:end'),
                order.indexOf('warehouseStatus:end'),
                order.indexOf('captured:end')
            )
            expect(lastStart).toBeLessThan(firstEnd)
        })
    })

    describe('queueInvocationResultsAndFlush', () => {
        it('queues across all sub-services then flushes all of them', async () => {
            const callOrder: string[] = []
            monitoringService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('monitoring.queue')
            })
            invocationResultsRowsService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('invocationResults.queue')
            })
            warehouseWebhooksService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('warehouse.queue')
            })
            warehouseWebhookStatusService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('warehouseStatus.queue')
            })
            capturedEventsService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('captured.queue')
                return Promise.resolve()
            })
            monitoringService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('monitoring.flush')
                return Promise.resolve()
            })
            invocationResultsRowsService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('invocationResults.flush')
                return Promise.resolve()
            })
            warehouseWebhooksService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('warehouse.flush')
                return Promise.resolve()
            })
            warehouseWebhookStatusService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('warehouseStatus.flush')
                return Promise.resolve()
            })
            capturedEventsService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('captured.flush')
                return Promise.resolve()
            })

            await service.queueInvocationResultsAndFlush(results)

            // All queue calls must complete before any flush call starts.
            const lastQueueIdx = Math.max(
                callOrder.indexOf('monitoring.queue'),
                callOrder.indexOf('invocationResults.queue'),
                callOrder.indexOf('warehouse.queue'),
                callOrder.indexOf('warehouseStatus.queue'),
                callOrder.indexOf('captured.queue')
            )
            const firstFlushIdx = Math.min(
                callOrder.indexOf('monitoring.flush'),
                callOrder.indexOf('invocationResults.flush'),
                callOrder.indexOf('warehouse.flush'),
                callOrder.indexOf('warehouseStatus.flush'),
                callOrder.indexOf('captured.flush')
            )
            expect(firstFlushIdx).toBeGreaterThan(lastQueueIdx)
        })
    })

    describe('exposed sub-services', () => {
        it('exposes the underlying services as public readonly fields', () => {
            expect(service.monitoringService).toBe(monitoringService)
            expect(service.invocationResultsRowsService).toBe(invocationResultsRowsService)
            expect(service.warehouseWebhooksService).toBe(warehouseWebhooksService)
            expect(service.warehouseWebhookStatusService).toBe(warehouseWebhookStatusService)
            expect(service.capturedEventsService).toBe(capturedEventsService)
        })
    })
})
