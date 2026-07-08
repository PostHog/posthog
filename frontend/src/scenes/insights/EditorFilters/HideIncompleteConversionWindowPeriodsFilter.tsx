import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { isFunnelsQuery } from '~/queries/utils'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function HideIncompleteConversionWindowPeriodsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isFunnelsQuery(querySource)) {
        return null
    }

    const hideIncompleteConversionWindowPeriods =
        querySource.funnelsFilter?.hideIncompleteConversionWindowPeriods ?? false

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={() =>
                updateInsightFilter({
                    hideIncompleteConversionWindowPeriods: !hideIncompleteConversionWindowPeriods,
                })
            }
            checked={hideIncompleteConversionWindowPeriods}
            label={
                <span className="font-normal inline-flex items-center gap-1">
                    Hide incomplete periods
                    <Tooltip title="Hides recent periods whose conversion window hasn't fully elapsed, so the trend isn't dragged down by entrants who still have time to convert.">
                        <IconInfo className="relative top-0.5 text-base text-secondary" />
                    </Tooltip>
                </span>
            }
            size="small"
        />
    )
}
