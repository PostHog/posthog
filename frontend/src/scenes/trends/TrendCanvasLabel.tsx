import { IconTestTube } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

export function TrendCanvasLabel(): JSX.Element | null {
    const { insight, supportsCreatingExperiment } = useValues(insightLogic)

    if (!insight?.query || !supportsCreatingExperiment) {
        return null
    }

    return (
        <div className="flex items-center">
            <LemonButton
                icon={<IconTestTube />}
                type="secondary"
                size="xsmall"
                to={urls.experiment('new', {
                    insight: insight.short_id ?? undefined,
                    name: (insight.name || insight.derived_name) ?? undefined,
                })}
            >
                Run Experiment
            </LemonButton>
        </div>
    )
}
