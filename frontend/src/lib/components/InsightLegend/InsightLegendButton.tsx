import './InsightLegendButton.scss'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { IconLegend } from 'lib/lemon-ui/icons'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { TrendsFilterType } from '~/types'
import { shouldShowLegend } from './utils'

export function InsightLegendButtonDataExploration(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter, hasLegend } = useValues(insightDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightDataLogic(insightProps))

    const showLegend = (insightFilter as TrendsFilterType)?.show_legend
    const toggleShowLegend = (): void => {
        updateInsightFilter({ show_legend: !showLegend })
    }

    return (
        <InsightLegendButtonComponent
            hasLegend={hasLegend}
            showLegend={showLegend}
            toggleShowLegend={toggleShowLegend}
        />
    )
}

export function InsightLegendButton(): JSX.Element | null {
    const { filters } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)

    const hasLegend = shouldShowLegend(filters)
    const showLegend = (filters as TrendsFilterType).show_legend

    return (
        <InsightLegendButtonComponent
            hasLegend={hasLegend}
            showLegend={showLegend}
            toggleShowLegend={toggleInsightLegend}
        />
    )
}

type InsightLegendButtonComponentProps = {
    hasLegend: boolean
    showLegend?: boolean
    toggleShowLegend: () => void
}

export function InsightLegendButtonComponent({
    hasLegend,
    showLegend,
    toggleShowLegend,
}: InsightLegendButtonComponentProps): JSX.Element | null {
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
