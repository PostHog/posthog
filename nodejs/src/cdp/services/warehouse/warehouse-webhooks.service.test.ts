import { IngestionOutputs } from '../../../ingestion/outputs/ingestion-outputs'
import { parseJSON } from '../../../utils/json-parse'
import { WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT, WarehouseSourceWebhooksOutput } from '../../outputs/outputs'
import { CyclotronJobInvocationResult, WarehouseWebhookPayload } from '../../types'
import { WarehouseWebhooksService } from './warehouse-webhooks.service'

const buildPayload = (overrides: Partial<WarehouseWebhookPayload> = {}): WarehouseWebhookPayload => ({
    team_id: 1,
    schema_id: 'schema-a',
    payload: { foo: 'bar' },
    ...overrides,
})

const buildResult = (warehouseWebhookPayloads: WarehouseWebhookPayload[]): CyclotronJobInvocationResult =>
    ({ warehouseWebhookPayloads }) as unknown as CyclotronJobInvocationResult

describe('WarehouseWebhooksService', () => {
    let outputs: jest.Mocked<IngestionOutputs<WarehouseSourceWebhooksOutput>>
    let service: WarehouseWebhooksService

    beforeEach(() => {
        outputs = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<IngestionOutputs<WarehouseSourceWebhooksOutput>>

        service = new WarehouseWebhooksService(outputs)
    })

    describe('queue + flush', () => {
        it('produces queued payloads on flush, encoded with key=team:schema and JSON-serialised value', async () => {
            const payload = buildPayload({ team_id: 42, schema_id: 'schema-x', payload: { a: 1, nested: { b: 2 } } })
            service.queue([payload])

            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(1)
            const call = outputs.produce.mock.calls[0]
            expect(call[0]).toBe(WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT)
            expect(call[1].key).toEqual(Buffer.from('42:schema-x'))
            expect(parseJSON((call[1].value as Buffer).toString())).toEqual({
                schema_id: 'schema-x',
                team_id: 42,
                payload: JSON.stringify({ a: 1, nested: { b: 2 } }),
            })
        })

        it('produces one message per queued payload', async () => {
            service.queue([buildPayload({ schema_id: 'a' }), buildPayload({ schema_id: 'b' })])
            service.queue([buildPayload({ schema_id: 'c' })])

            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(3)
        })

        it('clears the buffer after flush', async () => {
            service.queue([buildPayload()])
            await service.flush()
            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })

        it('queue([]) is a no-op', async () => {
            service.queue([])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('flush with empty buffer does not call outputs.produce', async () => {
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('swallows produce errors so one bad payload does not block the rest', async () => {
            outputs.produce.mockRejectedValueOnce(new Error('kafka down'))
            service.queue([buildPayload({ schema_id: 'a' }), buildPayload({ schema_id: 'b' })])

            await expect(service.flush()).resolves.toBeUndefined()
            expect(outputs.produce).toHaveBeenCalledTimes(2)
        })
    })

    describe('queueInvocationResults', () => {
        it('extracts warehouseWebhookPayloads from each result and queues them', async () => {
            const p1 = buildPayload({ schema_id: 'a' })
            const p2 = buildPayload({ schema_id: 'b' })
            const p3 = buildPayload({ schema_id: 'c' })

            service.queueInvocationResults([buildResult([p1, p2]), buildResult([p3])])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(3)
        })

        it('skips results with empty / undefined warehouseWebhookPayloads', async () => {
            service.queueInvocationResults([
                { warehouseWebhookPayloads: [] } as unknown as CyclotronJobInvocationResult,
                { warehouseWebhookPayloads: undefined } as unknown as CyclotronJobInvocationResult,
            ])
            await service.flush()

            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('handles an empty result array', async () => {
            service.queueInvocationResults([])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })
    })
})
