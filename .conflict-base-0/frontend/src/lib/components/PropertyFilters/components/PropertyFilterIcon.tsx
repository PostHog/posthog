import { IconBuilding, IconPeople, IconPerson, IconPiggyBank } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'

import { PropertyFilterType } from '~/types'

export function PropertyFilterIcon({ type }: { type?: PropertyFilterType }): JSX.Element | null {
    switch (type) {
        case 'event':
            return (
                <Tooltip title="Event property">
                    <IconUnverifiedEvent />
                </Tooltip>
            )
        case 'person':
            return (
                <Tooltip title="Person property">
                    <IconPerson />
                </Tooltip>
            )
        case 'cohort':
            return (
                <Tooltip title="Cohort filter">
                    <IconPeople />
                </Tooltip>
            )
        case 'group':
            return (
                <Tooltip title="Group filter">
                    <IconBuilding />
                </Tooltip>
            )
        case 'revenue_analytics':
            return (
                <Tooltip title="Revenue analytics filter">
                    <IconPiggyBank />
                </Tooltip>
            )
        default:
            return null
    }
}
