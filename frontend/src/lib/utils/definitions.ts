import { STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { EventDefinition, PropertyDefinition } from '~/types'

export const isDefinitionStale = (definition?: EventDefinition | PropertyDefinition): boolean => {
    const parsedLastSeen = definition?.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
}
