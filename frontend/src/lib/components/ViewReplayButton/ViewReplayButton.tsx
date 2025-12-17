import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Tooltip } from '@posthog/lemon-ui'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { RecordingUniversalFilters, ReplayTabs } from '~/types'

/**
 * Unified button component for navigating to Session Replay.
 *
 * Supports two modes:
 * 1. Filtered list mode: Opens replay with filters applied (for exploring recordings)
 * 2. Single recording mode: Opens a specific recording by ID
 *
 * @example
 * // Open replay with filters
 * <ViewReplayButton
 *   filters={{ filter_group: {...} }}
 *   label="View recordings"
 * />
 *
 * @example
 * // Open a specific recording
 * <ViewReplayButton
 *   recordingId="abc123"
 * />
 */

type ViewReplayButtonBaseProps = {
    label?: string
    tooltip?: string
} & Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'loading' | 'disabled' | 'disabledReason'>

type ViewReplayButtonFilteredProps = ViewReplayButtonBaseProps & {
    /** Filters to apply when opening replay (opens filtered list) */
    filters: Partial<RecordingUniversalFilters>
    recordingId?: never
}

type ViewReplayButtonSingleProps = ViewReplayButtonBaseProps & {
    /** ID of a specific recording to open (opens single recording) */
    recordingId: string
    filters?: never
}

type ViewReplayButtonProps = ViewReplayButtonFilteredProps | ViewReplayButtonSingleProps

export function ViewReplayButton({
    filters,
    recordingId,
    label,
    tooltip,
    ...buttonProps
}: ViewReplayButtonProps): JSX.Element {
    const onClick = (): void => {
        let replayUrl: string

        if (recordingId) {
            // Single recording mode: open specific recording
            replayUrl = urls.replaySingle(recordingId)
        } else {
            // Filtered list mode: open replay with filters
            replayUrl = urls.replay(ReplayTabs.Home, filters)
        }

        newInternalTab(replayUrl)
    }

    // Default label based on mode
    const defaultLabel = recordingId ? 'View recording' : 'View recordings'

    const button = (
        <LemonButton onClick={onClick} sideIcon={<IconRewindPlay />} {...buttonProps}>
            {label ?? defaultLabel}
        </LemonButton>
    )

    if (tooltip) {
        return <Tooltip title={tooltip}>{button}</Tooltip>
    }

    return button
}
