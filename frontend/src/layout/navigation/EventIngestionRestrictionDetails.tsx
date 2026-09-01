import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { EventIngestionRestriction, RestrictionType } from 'lib/logic/eventIngestionRestrictionLogic'

import type { PipelinesEnumApi } from '~/generated/core/api.schemas'

interface RestrictionEffect {
    label: string
    description: string
}

const RESTRICTION_EFFECTS: Partial<Record<string, RestrictionEffect>> = {
    [RestrictionType.DROP_EVENT_FROM_INGESTION]: {
        label: 'Events dropped',
        description: 'Matching events are not stored. This data is lost and cannot be recovered.',
    },
    [RestrictionType.FORCE_OVERFLOW_FROM_INGESTION]: {
        label: 'Processing delayed',
        description: 'Matching events are routed to a slower queue. They still arrive, but may take longer to appear.',
    },
    [RestrictionType.SKIP_PERSON_PROCESSING]: {
        label: 'Person processing disabled',
        description:
            'Matching events are stored, but person profiles and properties are not created or updated from them.',
    },
    [RestrictionType.REDIRECT_TO_DLQ]: {
        label: 'Events held',
        description:
            'Matching events are set aside and not processed. Contact support to find out whether they can be recovered.',
    },
    [RestrictionType.REDIRECT_TO_TOPIC]: {
        label: 'Events rerouted',
        description: 'Matching events take a different processing path. They may be delayed.',
    },
}

const UNKNOWN_EFFECT: RestrictionEffect = {
    label: 'Restricted',
    description: 'Matching events are handled differently from normal. Contact support for details.',
}

const PIPELINE_LABELS: Record<PipelinesEnumApi, string> = {
    analytics: 'analytics',
    session_recordings: 'session recordings',
    errortracking: 'error tracking',
    clientwarnings: 'client warnings',
    ai: 'AI',
}

const MAX_VALUES_SHOWN = 20

interface ScopeFilter {
    label: string
    values: string[]
}

function scopeFilters(restriction: EventIngestionRestriction): ScopeFilter[] {
    return [
        { label: 'distinct ID', values: restriction.distinct_ids ?? [] },
        { label: 'session ID', values: restriction.session_ids ?? [] },
        { label: 'event name', values: restriction.event_names ?? [] },
        { label: 'event UUID', values: restriction.event_uuids ?? [] },
    ].filter((filter) => filter.values.length > 0)
}

function ScopeFilterValues({ filter }: { filter: ScopeFilter }): JSX.Element {
    const hidden = filter.values.length - MAX_VALUES_SHOWN
    return (
        <div>
            <div className="text-secondary text-xs mb-1">
                Only {filter.values.length === 1 ? 'this' : `these ${filter.values.length}`} {filter.label}
                {filter.values.length === 1 ? '' : 's'}:
            </div>
            <div className="flex flex-wrap gap-1">
                {filter.values.slice(0, MAX_VALUES_SHOWN).map((value) => (
                    <LemonTag key={value} type="muted" size="small" className="font-mono break-all">
                        {value}
                    </LemonTag>
                ))}
                {hidden > 0 && <span className="text-secondary text-xs">and {hidden} more</span>}
            </div>
        </div>
    )
}

/** Explains each active ingestion restriction: what it does to matching events and which events it targets. */
export function EventIngestionRestrictionDetails({
    restrictions,
}: {
    restrictions: EventIngestionRestriction[]
}): JSX.Element {
    if (restrictions.length === 0) {
        return <p>No active restrictions were found for this project. Refresh the page to check again.</p>
    }

    return (
        <div className="deprecated-space-y-4">
            <p>
                PostHog has applied one or more restrictions to events sent with this project's token. Restrictions are
                usually put in place to protect the ingestion pipeline. Contact support if you need one removed.
            </p>
            <ul className="deprecated-space-y-3">
                {restrictions.map((restriction) => {
                    const effect = RESTRICTION_EFFECTS[restriction.restriction_type] ?? UNKNOWN_EFFECT
                    const filters = scopeFilters(restriction)
                    const pipelines = (restriction.pipelines ?? []).map(
                        (pipeline) => PIPELINE_LABELS[pipeline] ?? pipeline
                    )
                    const isScoped = filters.length > 0
                    return (
                        <li key={restriction.restriction_type} className="border rounded p-3">
                            <div className="flex items-center gap-2 mb-1">
                                <LemonTag type={isScoped ? 'warning' : 'danger'}>{effect.label}</LemonTag>
                                <span className="text-secondary text-xs">
                                    {isScoped ? 'Applies to some events' : 'Applies to all events'}
                                    {pipelines.length > 0 ? ` in ${pipelines.join(', ')}` : ''}
                                </span>
                            </div>
                            <p className="mb-0">{effect.description}</p>
                            {isScoped && (
                                <div className="mt-2 deprecated-space-y-2">
                                    {filters.length > 1 && (
                                        <div className="text-secondary text-xs">
                                            An event is affected only when it matches every filter below.
                                        </div>
                                    )}
                                    {filters.map((filter) => (
                                        <ScopeFilterValues key={filter.label} filter={filter} />
                                    ))}
                                </div>
                            )}
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
