import { STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { EventDefinition, PropertyDefinition } from '~/types'

export const isDefinitionStale = (
    definition?: EventDefinition | PropertyDefinition,
    staleSeconds: number = STALE_EVENT_SECONDS
): boolean => {
    const parsedLastSeen = definition?.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > staleSeconds
}
