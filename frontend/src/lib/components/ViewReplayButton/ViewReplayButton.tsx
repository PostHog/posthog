import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Tooltip } from '@posthog/lemon-ui'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { RecordingUniversalFilters, ReplayTabs } from '~/types'

/**
 * Unified button component for navigating to Session Replay.
 */

type ViewReplayButtonProps = {
    filters: Partial<RecordingUniversalFilters>
    label?: string
    tooltip?: string
} & Pick<
    LemonButtonProps,
    | 'size'
    | 'type'
    | 'data-attr'
    | 'fullWidth'
    | 'className'
    | 'icon'
    | 'sideIcon'
    | 'loading'
    | 'disabled'
    | 'disabledReason'
>

export function ViewReplayButton({
    filters,
    label = 'View recordings',
    tooltip,
    icon,
    sideIcon,
    ...buttonProps
}: ViewReplayButtonProps): JSX.Element {
    const onClick = (): void => {
        // Open replay with filters in a new PostHog internal tab
        const replayUrl = urls.replay(ReplayTabs.Home, filters)
        newInternalTab(replayUrl)
    }

    const button = (
        <LemonButton onClick={onClick} icon={icon} sideIcon={sideIcon ?? <IconRewindPlay />} {...buttonProps}>
            {label}
        </LemonButton>
    )

    if (tooltip) {
        return <Tooltip title={tooltip}>{button}</Tooltip>
    }

    return button
}
