import { useValues } from 'kea'

import { Dot, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { unwatchedIndicatorAriaLabel, unwatchedIndicatorTooltip } from './unwatchedIndicatorTooltip'

export function QuillUnwatchedIndicator({ otherViewersCount }: { otherViewersCount: number }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isExcludedFromHideRecordingsMenu = !!featureFlags[FEATURE_FLAGS.REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU]
    const watchedByOthers = !isExcludedFromHideRecordingsMenu && otherViewersCount > 0

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        className="inline-flex"
                        aria-label={unwatchedIndicatorAriaLabel(otherViewersCount, isExcludedFromHideRecordingsMenu)}
                    />
                }
            >
                <Dot variant={watchedByOthers ? 'info' : 'destructive'} />
            </TooltipTrigger>
            <TooltipContent>
                {unwatchedIndicatorTooltip(otherViewersCount, isExcludedFromHideRecordingsMenu)}
            </TooltipContent>
        </Tooltip>
    )
}
