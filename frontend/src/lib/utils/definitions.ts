import { STALE_EVENT_DAYS, STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { EventDefinition, PropertyDefinition, TeamPublicType } from '~/types'

export const isDefinitionStale = (
    definition?: EventDefinition | PropertyDefinition,
    staleSeconds: number = STALE_EVENT_SECONDS
): boolean => {
    const parsedLastSeen = definition?.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > staleSeconds
}

/**
 * How long a project waits before it calls an event stale. Teams that send events every day can
 * shorten the wait, so a dead event shows up in days rather than in a month.
 */
export const staleEventSeconds = (team?: TeamPublicType | null): number =>
    (team?.data_management_config?.stale_event_days ?? STALE_EVENT_DAYS) * 24 * 60 * 60
