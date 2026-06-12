import { PluginEvent } from '~/plugin-scaffold'

import { PipelineWarning } from '../pipelines/pipeline.interface'
import { PipelineResult, dlq, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HandleClientIngestionWarningStepInput {
    event: PluginEvent
}

// Cap persisted client-controlled strings so engineered payloads can't bloat warning rows or limiter keys.
const MAX_DETAIL_STRING_LENGTH = 200
const MAX_MESSAGE_LENGTH = 1000

interface SanitizedOverride {
    /** Rebuilt details to persist, never the raw client payload. */
    details: Record<string, unknown>
    debounceKey: string
}

// Allowlisted warning-type overrides: each sanitizer rebuilds only the details its renderer needs,
// or returns null to fall back to the generic type. A Map, not an object, so a forged type like
// `__proto__` can't reach Object.prototype.
const WARNING_TYPE_OVERRIDES = new Map<string, (details: Record<string, unknown>) => SanitizedOverride | null>([
    // emitted by capture when a replay snapshot batch is too large to ingest
    [
        'replay_message_too_large',
        (details) => {
            const replayRecord = isPlainObject(details.replayRecord) ? details.replayRecord : undefined
            const sessionId = boundedString(replayRecord?.session_id)
            const timestamp = boundedString(details.timestamp)
            if (sessionId === null || timestamp === null) {
                return null
            }
            return {
                details: {
                    timestamp,
                    replayRecord: { session_id: sessionId },
                    snapshotBytes: finiteNumber(details.snapshotBytes),
                    snapshotItemsCount: finiteNumber(details.snapshotItemsCount),
                    lib: boundedString(details.lib) ?? undefined,
                },
                debounceKey: sessionId,
            }
        },
    ],
    // emitted by capture when a replay payload fails validation
    [
        'replay_message_invalid',
        (details) => {
            const reason = boundedString(details.reason)
            if (reason === null) {
                return null
            }
            const sessionId = boundedString(details.sessionId)
            return {
                details: { reason, sessionId: sessionId ?? undefined },
                debounceKey: sessionId ?? reason,
            }
        },
    ],
])

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function boundedString(value: unknown, maxLength: number = MAX_DETAIL_STRING_LENGTH): string | null {
    return typeof value === 'string' && value.length > 0 && value.length <= maxLength ? value : null
}

function finiteNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function createHandleClientIngestionWarningStep<
    TInput extends HandleClientIngestionWarningStepInput,
>(): ProcessingStep<TInput, void> {
    return async function handleClientIngestionWarningStep(input: TInput): Promise<PipelineResult<void>> {
        const event = input.event

        if (event.event !== '$$client_ingestion_warning') {
            return Promise.resolve(
                dlq('unexpected_event_type', new Error(`Expected $$client_ingestion_warning, got ${event.event}`))
            )
        }

        // never persist raw client JSON
        const message = boundedString(event.properties?.$$client_ingestion_warning_message, MAX_MESSAGE_LENGTH)
        const baseDetails = {
            eventUuid: event.uuid,
            event: event.event,
            distinctId: event.distinct_id,
        }

        let warning: PipelineWarning = {
            type: 'client_ingestion_warning',
            details: { ...baseDetails, message: message ?? undefined },
            alwaysSend: true,
        }

        const requestedType = event.properties?.$$client_ingestion_warning_type
        const extraDetails = event.properties?.$$client_ingestion_warning_details
        const sanitize = typeof requestedType === 'string' ? WARNING_TYPE_OVERRIDES.get(requestedType) : undefined
        if (sanitize && isPlainObject(extraDetails)) {
            const override = sanitize(extraDetails)
            if (override) {
                warning = {
                    type: requestedType as string,
                    details: {
                        ...override.details,
                        ...baseDetails,
                        message: message ?? undefined,
                    },
                    key: override.debounceKey,
                }
            }
        }

        return ok(undefined, [], [warning])
    }
}
