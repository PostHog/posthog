import { IconCode } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { IconAdsClick, IconExclamation, IconEyeHidden, IconEyeVisible } from 'lib/lemon-ui/icons'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from 'lib/taxonomy'

import { EventType } from '~/types'

type EventIconProps = { event: EventType }

export const EventIcon = ({ event }: EventIconProps): JSX.Element => {
    let Component
    switch (event.event) {
        case '$pageview':
            Component = IconEyeVisible
            break
        case '$pageleave':
            Component = IconEyeHidden
            break
        case '$autocapture':
            Component = IconAdsClick
            break
        case '$rageclick':
            Component = IconExclamation
            break
        default:
            Component = IconCode
    }
    return (
        <Tooltip title={`${CORE_FILTER_DEFINITIONS_BY_GROUP.events[event.event]?.label || 'Custom'} event`}>
            <span>
                <Component className="text-2xl text-muted" />
            </span>
        </Tooltip>
    )
}
