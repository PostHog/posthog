import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { maxContextLogic } from 'scenes/max/maxContextLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { insightLogic } from './insightLogic'
import { insightVizDataLogic } from './insightVizDataLogic'

export function InsightAIAnalysis(): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { addOrUpdateContextInsight } = useActions(maxContextLogic)

    if (!insight.id) {
        return null
    }

    // Max's auto-collected scene context drops the insight when `short_id` or `query` is missing,
    // so without an explicit attach Max would autoRun against an empty context and silently stall.
    const explainInsight = (): void => {
        addOrUpdateContextInsight(insight)
        openSidePanel(SidePanelTab.Max, '!Explain this insight')
    }

    let disabledReason: string | undefined
    if (insightDataLoading) {
        disabledReason = 'Please wait for the insight to finish loading'
    } else if (!insight.short_id || !insight.query) {
        disabledReason = 'This insight has no query to explain yet'
    }

    return (
        <div className="mt-4 mb-4">
            <h2 className="font-semibold text-lg m-0 mb-2 flex items-center gap-2">AI analysis</h2>
            <p className="text-muted mb-4">
                Get AI-powered insights about your data, including trends, patterns, and actionable recommendations.
            </p>
            <div className="flex gap-2 flex-wrap">
                <AIConsentPopoverWrapper onApprove={explainInsight}>
                    <LemonButton
                        type="secondary"
                        onClick={explainInsight}
                        sideIcon={null}
                        data-attr="insight-ai-explain-button"
                        disabledReason={disabledReason}
                    >
                        Explain this insight
                    </LemonButton>
                </AIConsentPopoverWrapper>
            </div>
        </div>
    )
}
