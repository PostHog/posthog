import { parseJSON } from '~/common/utils/json-parse'
import { aiOtelGroupsCounter } from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'

export const STRIP_ATTRIBUTES = new Set([
    'telemetry.sdk.language',
    'gen_ai.operation.name',
    'posthog.ai.debug',
    'user.id',
    'posthog.distinct_id',
    'llm.request.type',
])

// Upper bound on the serialized size of a string-valued `$groups` attribute we
// will parse. A groups map is only a handful of short group-type → key pairs,
// so this is generous; it keeps a pathological payload out of parseJSON.
const MAX_GROUPS_LENGTH = 10_000

type GroupsOutcome = 'parsed' | 'non_object' | 'malformed' | 'too_large'

export function normalizeGroups(event: PluginEvent): void {
    const props = event.properties!
    if (typeof props.$groups !== 'string') {
        return
    }

    if (props.$groups.length > MAX_GROUPS_LENGTH) {
        delete props.$groups
        aiOtelGroupsCounter.labels({ outcome: 'too_large' }).inc()
        return
    }

    let outcome: GroupsOutcome
    try {
        const parsed = parseJSON(props.$groups)
        if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
            props.$groups = parsed
            outcome = 'parsed'
        } else {
            outcome = 'non_object'
        }
    } catch {
        outcome = 'malformed'
    }
    aiOtelGroupsCounter.labels({ outcome }).inc()
}

export function otelSpanDurationNanos(props: Record<string, unknown>): bigint | undefined {
    const startStr = props['$otel_start_time_unix_nano']
    const endStr = props['$otel_end_time_unix_nano']
    if (typeof startStr !== 'string' || typeof endStr !== 'string') {
        return undefined
    }
    try {
        const duration = BigInt(endStr) - BigInt(startStr)
        return duration > 0n ? duration : undefined
    } catch {
        // Ignore malformed nanosecond timestamps
        return undefined
    }
}
