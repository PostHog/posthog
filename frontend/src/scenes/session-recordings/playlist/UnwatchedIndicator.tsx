import './UnwatchedIndicator.scss'

import clsx from 'clsx'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function UnwatchedIndicator({ otherViewersCount }: { otherViewersCount: number }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const isExcludedFromHideRecordingsMenu = featureFlags[FEATURE_FLAGS.REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU]

    // If person wished to be excluded from the hide recordings menu, we don't show the tooltip
    const tooltip = isExcludedFromHideRecordingsMenu ? (
        <span>You have not watched this recording yet.</span>
    ) : otherViewersCount ? (
        <span>
            You have not watched this recording yet. {otherViewersCount} other{' '}
            {otherViewersCount === 1 ? 'person has' : 'people have'}.
        </span>
    ) : (
        <span>Nobody has watched this recording yet.</span>
    )

    return (
        <Tooltip title={tooltip}>
            <div
                className={clsx(
                    'UnwatchedIndicator w-2 h-2 rounded-full',
                    isExcludedFromHideRecordingsMenu
                        ? 'UnwatchedIndicator--primary'
                        : otherViewersCount
                          ? 'UnwatchedIndicator--secondary'
                          : 'UnwatchedIndicator--primary'
                )}
                aria-label={
                    isExcludedFromHideRecordingsMenu
                        ? 'unwatched-recording-by-you-label'
                        : otherViewersCount
                          ? 'unwatched-recording-by-you-label'
                          : 'unwatched-recording-by-everyone-label'
                }
            />
        </Tooltip>
    )
}
