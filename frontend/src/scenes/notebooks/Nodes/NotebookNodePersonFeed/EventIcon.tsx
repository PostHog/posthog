import { Tooltip } from '@posthog/lemon-ui'
import { IconAdsClick, IconCode, IconExclamation, IconEyeHidden, IconEyeVisible } from 'lib/lemon-ui/icons'
import { KEY_MAPPING } from 'lib/taxonomy'

import { EventType } from '~/types'

type EventIconProps = { event: EventType }

export const EventIcon = ({ event }: EventIconProps): JSX.Element => {
    let Component: React.ComponentType<{ className: string }>
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
        <Tooltip title={`${KEY_MAPPING.event[event.event]?.label || 'Custom'} event`}>
            <Component className="text-2xl text-muted" />
        </Tooltip>
    )
}
