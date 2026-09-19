import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'

export interface WarnMissingSessionIdInput {
    normalizedEvent: PluginEvent
}

/**
 * Reports events that carry a $window_id but no usable $session_id.
 *
 * The web SDK reads both ids from one call, so an event that holds one and not the other
 * lost the session id somewhere between the SDK and here. Nothing else records that loss,
 * which leaves the team to discover broken session stitching, bounce rate, and replay
 * linkage on their own. The event is still ingested: the warning only makes the shape
 * countable per team.
 *
 * Runs after normalization so it reads the ids the event is written to ClickHouse with,
 * including any that cookieless mode or a transformation supplied or removed.
 */
export function createWarnMissingSessionIdStep<T extends WarnMissingSessionIdInput>(): ProcessingStep<T, T> {
    return function warnMissingSessionIdStep(input: T): Promise<PipelineResult<T>> {
        const { normalizedEvent } = input
        const properties = normalizedEvent.properties ?? {}

        if (!hasUsableId(properties['$window_id']) || hasUsableId(properties['$session_id'])) {
            return Promise.resolve(ok(input))
        }

        const warning: PipelineWarning = {
            type: 'missing_session_id_with_window_id',
            details: {
                eventUuid: normalizedEvent.uuid,
                event: normalizedEvent.event,
                distinctId: normalizedEvent.distinct_id,
                sessionIdType: describeValue(properties['$session_id']),
                libVersion: properties['$lib_version'],
                lib: properties['$lib'],
            },
        }

        return Promise.resolve(ok(input, [], [warning]))
    }
}

function hasUsableId(value: unknown): boolean {
    return typeof value === 'string' && value.trim().length > 0
}

// Tells the three shapes apart that all read as a missing id downstream, so the sender can be
// traced: a property the SDK never set, one it set to null, and one it set to an empty string.
function describeValue(value: unknown): string {
    if (value === undefined) {
        return 'absent'
    }
    if (value === null) {
        return 'null'
    }
    if (typeof value === 'string') {
        return 'empty_string'
    }
    return typeof value
}
