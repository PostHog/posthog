import { IconCohort, IconPerson, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { PropertyFilterType } from '~/types'

export function PropertyFilterIcon({ type }: { type?: PropertyFilterType }): JSX.Element {
    let iconElement = <></>
    switch (type) {
        case 'event':
            iconElement = (
                <Tooltip title="Event property">
                    <span>
                        <IconUnverifiedEvent />
                    </span>
                </Tooltip>
            )
            break
        case 'person':
            iconElement = (
                <Tooltip title="Person property">
                    <span>
                        <IconPerson />
                    </span>
                </Tooltip>
            )
            break
        case 'cohort':
            iconElement = (
                <Tooltip title="Cohort filter">
                    <span>
                        <IconCohort />
                    </span>
                </Tooltip>
            )
            break
    }
    return iconElement
}
