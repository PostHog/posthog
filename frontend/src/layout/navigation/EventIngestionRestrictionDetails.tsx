import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { EventIngestionRestriction, RestrictionType } from 'lib/logic/eventIngestionRestrictionLogic'

const RESTRICTION_EFFECTS: Record<RestrictionType, { label: string; description: string }> = {
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
}

const MAX_DISTINCT_IDS_SHOWN = 20

/** Explains each active ingestion restriction: what it does to matching events and which distinct IDs it targets. */
export function EventIngestionRestrictionDetails({
    restrictions,
}: {
    restrictions: EventIngestionRestriction[]
}): JSX.Element {
    const knownRestrictions = restrictions.filter((r) => r.restriction_type in RESTRICTION_EFFECTS)

    if (knownRestrictions.length === 0) {
        return <p>No active restrictions were found for this project. Refresh the page to check again.</p>
    }

    return (
        <div className="deprecated-space-y-4">
            <p>
                PostHog has applied one or more restrictions to events sent with this project's token. Restrictions are
                usually put in place to protect the ingestion pipeline. Contact support if you need one removed.
            </p>
            <ul className="deprecated-space-y-3">
                {knownRestrictions.map((restriction) => {
                    const effect = RESTRICTION_EFFECTS[restriction.restriction_type]
                    const distinctIds = restriction.distinct_ids ?? []
                    const scopedToDistinctIds = distinctIds.length > 0
                    return (
                        <li key={restriction.restriction_type} className="border rounded p-3">
                            <div className="flex items-center gap-2 mb-1">
                                <LemonTag type={scopedToDistinctIds ? 'warning' : 'danger'}>{effect.label}</LemonTag>
                                <span className="text-secondary text-xs">
                                    {scopedToDistinctIds
                                        ? `Applies to ${distinctIds.length} distinct ID${distinctIds.length === 1 ? '' : 's'}`
                                        : 'Applies to all events in this project'}
                                </span>
                            </div>
                            <p className="mb-0">{effect.description}</p>
                            {scopedToDistinctIds && (
                                <div className="mt-2 flex flex-wrap gap-1">
                                    {distinctIds.slice(0, MAX_DISTINCT_IDS_SHOWN).map((distinctId) => (
                                        <code key={distinctId} className="text-xs break-all">
                                            {distinctId}
                                        </code>
                                    ))}
                                    {distinctIds.length > MAX_DISTINCT_IDS_SHOWN && (
                                        <span className="text-secondary text-xs">
                                            and {distinctIds.length - MAX_DISTINCT_IDS_SHOWN} more
                                        </span>
                                    )}
                                </div>
                            )}
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
