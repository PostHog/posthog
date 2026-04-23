import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isTrendsQuery } from '~/queries/utils'

export function BoxPlotOutliersFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            label={
                <span>
                    Exclude outliers{' '}
                    <Tooltip title="When enabled, whiskers are clipped to 1.5x the interquartile range, making it easier to see differences between the quartiles. When disabled, the y-axis extends to show the full range including extreme values.">
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </span>
            }
            className="px-2 py-1"
            checked={trendsFilter?.excludeBoxPlotOutliers !== false}
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, excludeBoxPlotOutliers: checked },
                    })
                }
            }}
            fullWidth
        />
    )
}
