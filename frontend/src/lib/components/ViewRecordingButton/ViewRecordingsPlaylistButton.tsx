import { ReactNode } from 'react'

import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Tooltip } from '@posthog/lemon-ui'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { RecordingUniversalFilters, ReplayTabs } from '~/types'

type ViewRecordingsPlaylistButtonProps = {
    filters: Partial<RecordingUniversalFilters>
    label?: ReactNode
    tooltip?: ReactNode
    disabled?: boolean
    disabledReason?: string | JSX.Element | null
    onClick?: () => void
} & Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'loading'>

/**
 * Button for opening the Session Replay page with filters applied.
 * Opens in a new PostHog tab to view a filtered playlist of recordings.
 */
export default function ViewRecordingsPlaylistButton({
    filters,
    label = 'View recordings',
    tooltip,
    disabled,
    disabledReason,
    onClick: onClickCallback,
    ...buttonProps
}: ViewRecordingsPlaylistButtonProps): JSX.Element {
    const onClick = (): void => {
        onClickCallback?.()
        const url = urls.replay(ReplayTabs.Home, filters)
        newInternalTab(url)
    }

    const button = (
        <LemonButton
            onClick={onClick}
            sideIcon={<IconRewindPlay />}
            disabled={disabled}
            disabledReason={disabledReason}
            {...buttonProps}
        >
            {label}
        </LemonButton>
    )

    return tooltip ? <Tooltip title={tooltip}>{button}</Tooltip> : button
}
