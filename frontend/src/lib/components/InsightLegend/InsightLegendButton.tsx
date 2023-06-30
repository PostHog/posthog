import './InsightLegendButton.scss'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { IconLegend } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { TrendsFilterType } from '~/types'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function InsightLegendButton(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter, hasLegend } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showLegend = (insightFilter as TrendsFilterType)?.show_legend
    const toggleShowLegend = (): void => {
        updateInsightFilter({ show_legend: !showLegend })
    }

    if (!hasLegend) {
        return null
    }

    return (
        <Button className="InsightLegendButton" onClick={toggleShowLegend}>
            <IconLegend />
            <span className="InsightLegendButton-title">{showLegend ? 'Hide' : 'Show'} legend</span>
        </Button>
    )
}
