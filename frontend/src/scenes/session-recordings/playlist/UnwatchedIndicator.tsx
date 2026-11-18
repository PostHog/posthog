import './UnwatchedIndicator.scss'

import clsx from 'clsx'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { unwatchedIndicatorAriaLabel, unwatchedIndicatorTooltip } from './unwatchedIndicatorTooltip'

export function UnwatchedIndicator({ otherViewersCount }: { otherViewersCount: number }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isExcludedFromHideRecordingsMenu = !!featureFlags[FEATURE_FLAGS.REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU]

    return (
        <Tooltip title={unwatchedIndicatorTooltip(otherViewersCount, isExcludedFromHideRecordingsMenu)}>
            <div
                className={clsx(
                    'UnwatchedIndicator w-2 h-2 rounded-full',
                    isExcludedFromHideRecordingsMenu
                        ? 'UnwatchedIndicator--primary'
                        : otherViewersCount
                          ? 'UnwatchedIndicator--secondary'
                          : 'UnwatchedIndicator--primary'
                )}
                aria-label={unwatchedIndicatorAriaLabel(otherViewersCount, isExcludedFromHideRecordingsMenu)}
            />
        </Tooltip>
    )
}
