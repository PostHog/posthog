import { CyclotronJobInvocationResult } from '../types'
import { CapturedEventsService } from './captured-events/captured-events.service'
import { InvocationResultsService } from './invocation-results.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { WarehouseWebhooksService } from './warehouse/warehouse-webhooks.service'

describe('InvocationResultsService', () => {
    let monitoringService: jest.Mocked<HogFunctionMonitoringService>
    let warehouseWebhooksService: jest.Mocked<WarehouseWebhooksService>
    let capturedEventsService: jest.Mocked<CapturedEventsService>
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

        warehouseWebhooksService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<WarehouseWebhooksService>

        capturedEventsService = {
            queueInvocationResults: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CapturedEventsService>

        service = new InvocationResultsService(monitoringService, warehouseWebhooksService, capturedEventsService)
    })

    describe('queueInvocationResults', () => {
        it('fans the same results out to all three sub-services', async () => {
            await service.queueInvocationResults(results)

            expect(monitoringService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(monitoringService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(warehouseWebhooksService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(warehouseWebhooksService.queueInvocationResults).toHaveBeenCalledWith(results)
            expect(capturedEventsService.queueInvocationResults).toHaveBeenCalledTimes(1)
            expect(capturedEventsService.queueInvocationResults).toHaveBeenCalledWith(results)
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
        it('flushes all three sub-services', async () => {
            await service.flush()

            expect(monitoringService.flush).toHaveBeenCalledTimes(1)
            expect(warehouseWebhooksService.flush).toHaveBeenCalledTimes(1)
            expect(capturedEventsService.flush).toHaveBeenCalledTimes(1)
        })

        it('flushes all three in parallel (all start before any finish)', async () => {
            const order: string[] = []
            const trackOrder = (name: string) =>
                jest.fn().mockImplementation(() => {
                    order.push(`${name}:start`)
                    return Promise.resolve().then(() => {
                        order.push(`${name}:end`)
                    })
                })

            monitoringService.flush = trackOrder('monitoring')
            warehouseWebhooksService.flush = trackOrder('warehouse')
            capturedEventsService.flush = trackOrder('captured')

            await service.flush()

            // All three should have started before any of them finish — proves Promise.all parallelism.
            const lastStart = Math.max(
                order.indexOf('monitoring:start'),
                order.indexOf('warehouse:start'),
                order.indexOf('captured:start')
            )
            const firstEnd = Math.min(
                order.indexOf('monitoring:end'),
                order.indexOf('warehouse:end'),
                order.indexOf('captured:end')
            )
            expect(lastStart).toBeLessThan(firstEnd)
        })
    })

    describe('queueInvocationResultsAndFlush', () => {
        it('queues across all three then flushes all three', async () => {
            const callOrder: string[] = []
            monitoringService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('monitoring.queue')
            })
            warehouseWebhooksService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('warehouse.queue')
            })
            capturedEventsService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('captured.queue')
                return Promise.resolve()
            })
            monitoringService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('monitoring.flush')
                return Promise.resolve()
            })
            warehouseWebhooksService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('warehouse.flush')
                return Promise.resolve()
            })
            capturedEventsService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('captured.flush')
                return Promise.resolve()
            })

            await service.queueInvocationResultsAndFlush(results)

            // All three queue calls must complete before any flush call starts.
            const lastQueueIdx = Math.max(
                callOrder.indexOf('monitoring.queue'),
                callOrder.indexOf('warehouse.queue'),
                callOrder.indexOf('captured.queue')
            )
            const firstFlushIdx = Math.min(
                callOrder.indexOf('monitoring.flush'),
                callOrder.indexOf('warehouse.flush'),
                callOrder.indexOf('captured.flush')
            )
            expect(firstFlushIdx).toBeGreaterThan(lastQueueIdx)
        })
    })

    describe('exposed sub-services', () => {
        it('exposes the underlying services as public readonly fields', () => {
            expect(service.monitoringService).toBe(monitoringService)
            expect(service.warehouseWebhooksService).toBe(warehouseWebhooksService)
            expect(service.capturedEventsService).toBe(capturedEventsService)
        })
    })
})
