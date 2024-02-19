import { IconPerson } from '@posthog/icons'
import { IconCohort, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { PropertyFilterType } from '~/types'

export function PropertyFilterIcon({ type }: { type?: PropertyFilterType }): JSX.Element {
    let iconElement = <></>
    switch (type) {
        case 'event':
            iconElement = (
                <Tooltip title="Event property">
                    <IconUnverifiedEvent />
                </Tooltip>
            )
            break
        case 'person':
            iconElement = (
                <Tooltip title="Person property">
                    <IconPerson />
                </Tooltip>
            )
            break
        case 'cohort':
            iconElement = (
                <Tooltip title="Cohort filter">
                    <IconCohort />
                </Tooltip>
            )
            break
    }
    return iconElement
}
