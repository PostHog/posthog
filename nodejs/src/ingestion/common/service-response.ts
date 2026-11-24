import { Counter } from 'prom-client'
import { z } from 'zod'

import { INGESTION_WARNING_TYPES, IngestionWarningType } from '~/ingestion/common/ingestion-warning-types'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, dlq, drop } from '~/ingestion/framework/results'

// The contract is specified in rust/common/ingestion-response/README.md.
export const SERVICE_RESPONSE_HEADER = 'x-posthog-ingestion-response'
export const SERVICE_RESPONSE_VERSION = '1'

const itemErrorSchema = z.object({ code: z.string(), message: z.string() })

const itemWarningSchema = z.object({
    type: z.string(),
    details: z.record(z.string(), z.unknown()),
    key: z.string().optional(),
})

export type ItemError = z.infer<typeof itemErrorSchema>

export type ItemWarning = z.infer<typeof itemWarningSchema>

export type ItemResult<T> = (
    | { result: 'ok'; value: T }
    | { result: 'drop'; reason: string }
    | { result: 'retry'; error: ItemError }
    | { result: 'fail'; error: ItemError }
) & { warnings?: ItemWarning[] }

export class ServiceResponseError extends Error {
    constructor(
        message: string,
        readonly isRetriable: boolean
    ) {
        super(message)
        this.name = 'ServiceResponseError'
    }
}

const serviceItemFailures = new Counter({
    name: 'ingestion_service_item_failures_total',
    help: 'Items a service failed on their own, sent to the DLQ',
    labelNames: ['service', 'result', 'code'],
})

const serviceUnknownWarnings = new Counter({
    name: 'ingestion_service_unknown_warnings_total',
    help: 'Warnings from a service skipped because their type is not in the ingestion warnings registry',
    labelNames: ['service'],
})

export function respondedWithItemResults(headers: Record<string, string> | undefined): boolean {
    return headers?.[SERVICE_RESPONSE_HEADER]?.trim() === SERVICE_RESPONSE_VERSION
}

/** @throws ServiceResponseError, not retriable, when the body breaks the contract */
export function parseItemResults<T>(body: unknown, valueSchema: z.ZodType<T>, expectedLength: number): ItemResult<T>[] {
    const warnings = z.array(itemWarningSchema).optional()
    const schema = z.object({
        results: z.array(
            z.discriminatedUnion('result', [
                z.object({ result: z.literal('ok'), value: valueSchema, warnings }),
                z.object({ result: z.literal('drop'), reason: z.string(), warnings }),
                z.object({ result: z.literal('retry'), error: itemErrorSchema, warnings }),
                z.object({ result: z.literal('fail'), error: itemErrorSchema, warnings }),
            ])
        ),
    })
    const parsed = schema.safeParse(body)
    if (!parsed.success) {
        throw new ServiceResponseError(`Invalid item results: ${parsed.error.message}`, false)
    }
    if (parsed.data.results.length !== expectedLength) {
        throw new ServiceResponseError(
            `Item results length mismatch: got ${parsed.data.results.length}, expected ${expectedLength}`,
            false
        )
    }
    return parsed.data.results as ItemResult<T>[]
}

/**
 * Turns the item results of one batch into pipeline results, in order. A `fail` or `retry` item
 * goes to the DLQ as `<service>_item_fail` or `<service>_item_retry`, and each item's warnings
 * become ingestion warnings on its result.
 *
 * @throws ServiceResponseError, retriable, when a batch of more than one item asks for a retry on
 * every item. The contract treats that as a failure of the whole request, so an outage of the
 * service fails the batch instead of sending all of it to the DLQ. A batch of one item is exempt,
 * because an item that always asks for a retry would otherwise fail the batch on every attempt.
 * Pass the whole batch, not one HTTP response, because one response can hold a single slow item.
 */
export function toPipelineResults<T, O>(
    service: string,
    results: ItemResult<T>[],
    onOk: (value: T, index: number, warnings: PipelineWarning[]) => PipelineResult<O>
): PipelineResult<O>[] {
    if (results.length > 1 && results.every((item) => item.result === 'retry')) {
        throw new ServiceResponseError(`${service} asked to retry every item in the batch`, true)
    }

    return results.map((item, index) => {
        const warnings = toPipelineWarnings(service, item.warnings)
        switch (item.result) {
            case 'ok':
                return onOk(item.value, index, warnings)
            case 'drop':
                return drop(item.reason, [], warnings)
            case 'retry':
            case 'fail':
                serviceItemFailures.labels({ service, result: item.result, code: item.error.code }).inc()
                return dlq(
                    `${service}_item_${item.result}`,
                    new Error(`${item.error.code}: ${item.error.message}`),
                    [],
                    warnings
                )
        }
    })
}

function toPipelineWarnings(service: string, warnings: ItemWarning[] = []): PipelineWarning[] {
    return warnings.flatMap((warning) => {
        if (!isIngestionWarningType(warning.type)) {
            serviceUnknownWarnings.labels({ service }).inc()
            return []
        }
        return [{ type: warning.type, details: warning.details, key: warning.key }]
    })
}

function isIngestionWarningType(type: string): type is IngestionWarningType {
    return Object.hasOwn(INGESTION_WARNING_TYPES, type)
}
