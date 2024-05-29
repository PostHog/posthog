import { IconPerson } from '@posthog/icons'
import { IconCohort, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { AnyPropertyFilter } from '~/types'

import { isCohortPropertyFilter, isEventPropertyFilter, isPersonPropertyFilter, isRecordingEventFilter } from '../utils'

export function PropertyFilterIcon({ item }: { item?: AnyPropertyFilter }): JSX.Element {
    let iconElement = <></>

    if (isEventPropertyFilter(item) || isRecordingEventFilter(item)) {
        iconElement = (
            <Tooltip title="Event property">
                <IconUnverifiedEvent />
            </Tooltip>
        )
    } else if (isPersonPropertyFilter(item)) {
        iconElement = (
            <Tooltip title="Person property">
                <IconPerson />
            </Tooltip>
        )
    } else if (isCohortPropertyFilter(item)) {
        iconElement = (
            <Tooltip title="Cohort filter">
                <IconCohort />
            </Tooltip>
        )
    }
    return iconElement
}
