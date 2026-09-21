import { Attributes } from '@opentelemetry/api'

/**
 * Attributes that identify the tenant, actor and action of a step span, so slow spans can be
 * broken down by who caused them. The keys match the dimensions TopHog and the APM span store
 * already use, so the two can be joined by eye.
 */
export interface EventSpanAttributes extends Attributes {
    team_id?: number
    distinct_id?: string
    event?: string
}

type Loose = Record<string, unknown>

function asRecord(value: unknown): Loose | undefined {
    return value !== null && typeof value === 'object' ? (value as Loose) : undefined
}

/**
 * Derive span attributes from a step input by its well-known fields. Steps get many input shapes
 * (`team`, `teamId`, `event`, `normalizedEvent`, `preparedEvent`, ...), so this reads whatever is
 * present rather than making every step declare attributes. Unknown shapes yield `{}`.
 */
export function eventSpanAttributes(input: unknown): EventSpanAttributes {
    const record = asRecord(input)
    if (!record) {
        return {}
    }

    const event = asRecord(record.preparedEvent) ?? asRecord(record.normalizedEvent) ?? asRecord(record.event)
    const team = asRecord(record.team)

    const attrs: EventSpanAttributes = {}

    const teamId = team?.id ?? record.teamId ?? event?.team_id ?? event?.teamId
    if (typeof teamId === 'number') {
        attrs.team_id = teamId
    }

    const distinctId = event?.distinct_id ?? event?.distinctId
    if (typeof distinctId === 'string') {
        attrs.distinct_id = distinctId
    }

    const eventName = event?.event
    if (typeof eventName === 'string') {
        attrs.event = eventName
    }

    return attrs
}
