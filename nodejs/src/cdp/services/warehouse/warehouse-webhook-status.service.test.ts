import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { WAREHOUSE_WEBHOOK_DELIVERY_STATUS_OUTPUT, WarehouseWebhookDeliveryStatusOutput } from '../../outputs/outputs'
import { CyclotronJobInvocationResult } from '../../types'
import { WarehouseWebhookStatusService } from './warehouse-webhook-status.service'

type ResultOverrides = {
    type?: string
    sourceId?: string | null
    schemaId?: string | null
    status?: number
    body?: unknown
    error?: unknown
    omitHttpResponse?: boolean
}

const buildResult = (overrides: ResultOverrides = {}): CyclotronJobInvocationResult => {
    const inputs: Record<string, { value: unknown }> = {}
    if (overrides.sourceId !== null) {
        inputs.source_id = { value: overrides.sourceId ?? 'src-1' }
    }
    if (overrides.schemaId !== null) {
        inputs.schema_id = { value: overrides.schemaId ?? 'schema-1' }
    }

    const execResult = overrides.omitHttpResponse
        ? undefined
        : { httpResponse: { status: overrides.status ?? 200, body: overrides.body ?? 'ok' } }

    return {
        invocation: {
            teamId: 1,
            hogFunction: {
                type: overrides.type ?? 'warehouse_source_webhook',
                team_id: 1,
                inputs,
            },
        },
        execResult,
        error: overrides.error,
        finished: true,
        logs: [],
        metrics: [],
        capturedPostHogEvents: [],
        warehouseWebhookPayloads: [],
    } as unknown as CyclotronJobInvocationResult
}

const parsedRecords = (outputs: jest.Mocked<IngestionOutputs<WarehouseWebhookDeliveryStatusOutput>>): any[] =>
    outputs.produce.mock.calls.map((call) => parseJSON((call[1].value as Buffer).toString()))

describe('WarehouseWebhookStatusService', () => {
    let outputs: jest.Mocked<IngestionOutputs<WarehouseWebhookDeliveryStatusOutput>>
    let service: WarehouseWebhookStatusService

    beforeEach(() => {
        jest.useFakeTimers()
        outputs = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<IngestionOutputs<WarehouseWebhookDeliveryStatusOutput>>

        service = new WarehouseWebhookStatusService(outputs)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('record derivation', () => {
        it('produces a failing record for a 4xx response with the reason from a string body', async () => {
            service.queueInvocationResults([buildResult({ status: 400, body: 'Bad signature' })])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(1)
            const call = outputs.produce.mock.calls[0]
            expect(call[0]).toBe(WAREHOUSE_WEBHOOK_DELIVERY_STATUS_OUTPUT)
            expect(call[1].key).toEqual(Buffer.from('1:src-1'))
            const record = parseJSON((call[1].value as Buffer).toString())
            expect(record).toMatchObject({
                team_id: 1,
                source_id: 'src-1',
                schema_id: 'schema-1',
                http_status: 400,
                ok: 0,
                reason: 'Bad signature',
            })
            expect(typeof record.timestamp).toBe('string')
        })

        it('derives the reason from an object body error/message field', async () => {
            service.queueInvocationResults([buildResult({ status: 401, body: { error: 'Unauthorized' } })])
            service.queueInvocationResults([
                buildResult({ status: 403, body: { message: 'Forbidden' }, sourceId: 'src-2' }),
            ])
            await service.flush()

            const records = parsedRecords(outputs)
            expect(records.find((r) => r.source_id === 'src-1').reason).toBe('Unauthorized')
            expect(records.find((r) => r.source_id === 'src-2').reason).toBe('Forbidden')
        })

        it('truncates long reasons', async () => {
            service.queueInvocationResults([buildResult({ status: 400, body: 'x'.repeat(500) })])
            await service.flush()

            expect(parsedRecords(outputs)[0].reason).toHaveLength(200)
        })

        it('produces a healthy record (ok=1, empty reason) for a 2xx response', async () => {
            service.queueInvocationResults([buildResult({ status: 200 })])
            await service.flush()

            expect(parsedRecords(outputs)[0]).toMatchObject({ ok: 1, http_status: 200, reason: '' })
        })

        it('falls back to status 500 when there is a runtime error and no http response', async () => {
            service.queueInvocationResults([buildResult({ omitHttpResponse: true, error: 'boom' })])
            await service.flush()

            expect(parsedRecords(outputs)[0]).toMatchObject({ ok: 0, http_status: 500, reason: 'boom' })
        })

        it('emits an empty schema_id when the function has no schema_id input', async () => {
            service.queueInvocationResults([buildResult({ status: 400, body: 'Bad signature', schemaId: null })])
            await service.flush()

            expect(parsedRecords(outputs)[0].schema_id).toBe('')
        })
    })

    describe('records that are ignored', () => {
        it('skips non-warehouse_source_webhook functions', async () => {
            service.queueInvocationResults([buildResult({ type: 'source_webhook', status: 400 })])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('skips results without a source_id (can not attribute)', async () => {
            service.queueInvocationResults([buildResult({ status: 400, sourceId: null })])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('skips results with no http response and no error (e.g. queued for async work)', async () => {
            service.queueInvocationResults([buildResult({ omitHttpResponse: true })])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('skips invocations that are not hog functions', async () => {
            service.queueInvocationResults([
                {
                    invocation: { teamId: 1 },
                    execResult: { httpResponse: { status: 400 } },
                } as unknown as CyclotronJobInvocationResult,
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

    describe('success throttling', () => {
        it('throttles steady-state successes to one per source per window', async () => {
            service.queueInvocationResults([buildResult({ status: 200 })])
            service.queueInvocationResults([buildResult({ status: 200 })])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })

        it('emits a success again once the throttle window elapses', async () => {
            service.queueInvocationResults([buildResult({ status: 200 })])
            await service.flush()
            jest.advanceTimersByTime(61_000)
            service.queueInvocationResults([buildResult({ status: 200 })])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(2)
        })

        it('never throttles failures', async () => {
            service.queueInvocationResults([buildResult({ status: 400, body: 'Bad signature' })])
            service.queueInvocationResults([buildResult({ status: 400, body: 'Bad signature' })])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(2)
        })

        it('always emits the first success after a failure (the recovery transition)', async () => {
            service.queueInvocationResults([buildResult({ status: 400, body: 'Bad signature' })])
            service.queueInvocationResults([buildResult({ status: 200 })])
            await service.flush()

            const records = parsedRecords(outputs)
            expect(records).toHaveLength(2)
            expect(records[0].ok).toBe(0)
            expect(records[1].ok).toBe(1)
        })

        it('throttles per source independently', async () => {
            service.queueInvocationResults([buildResult({ status: 200, sourceId: 'src-a' })])
            service.queueInvocationResults([buildResult({ status: 200, sourceId: 'src-b' })])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(2)
        })
    })

    describe('flush', () => {
        it('clears the buffer after flush', async () => {
            service.queueInvocationResults([buildResult({ status: 400, body: 'Bad signature' })])
            await service.flush()
            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })

        it('swallows produce errors so one bad record does not block the rest', async () => {
            outputs.produce.mockRejectedValueOnce(new Error('kafka down'))
            service.queueInvocationResults([
                buildResult({ status: 400, body: 'Bad signature', sourceId: 'src-a' }),
                buildResult({ status: 400, body: 'Bad signature', sourceId: 'src-b' }),
            ])

            await expect(service.flush()).resolves.toBeUndefined()
            expect(outputs.produce).toHaveBeenCalledTimes(2)
        })
    })
})
