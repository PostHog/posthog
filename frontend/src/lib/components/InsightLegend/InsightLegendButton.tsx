import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { IconLegend } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFilterWithDisplay } from 'scenes/insights/sharedUtils'
import { shouldShowLegend } from './InsightLegend'

export function InsightLegendButton(): JSX.Element | null {
    const { filters } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)

    return shouldShowLegend(filters) && isFilterWithDisplay(filters) ? (
        <Button className="InsightLegendButton" onClick={toggleInsightLegend}>
            <IconLegend />
            <span className="InsightLegendButton-title">{filters.show_legend ? 'Hide' : 'Show'} legend</span>
        </Button>
    ) : null
}
