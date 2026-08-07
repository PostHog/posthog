import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { insightLogic } from './insightLogic'
import { insightVizDataLogic } from './insightVizDataLogic'

export function InsightAIAnalysis(): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    // The consent popover asks the user to approve AI data processing. Only reveal it once they've
    // actually clicked "Explain this insight" — gating on consent state alone made it auto-open over
    // the chart on every page load for orgs that hadn't approved yet.
    const [explainRequested, setExplainRequested] = useState(false)

    if (!insight.id) {
        return null
    }

    const explainInsight = (): void => openSidePanel(SidePanelTab.Max, '!Explain this insight')

    return (
        <div className="mt-4 mb-4">
            <h2 className="font-semibold text-lg m-0 mb-2 flex items-center gap-2">AI analysis</h2>
            <p className="text-muted mb-4">
                Get AI-powered insights about your data, including trends, patterns, and actionable recommendations.
            </p>
            <div className="flex gap-2 flex-wrap">
                <AIConsentPopoverWrapper
                    ignoreDismissal
                    hidden={dataProcessingAccepted || !explainRequested}
                    onApprove={() => {
                        setExplainRequested(false)
                        explainInsight()
                    }}
                    onDismiss={() => setExplainRequested(false)}
                >
                    <LemonButton
                        type="secondary"
                        onClick={() => (dataProcessingAccepted ? explainInsight() : setExplainRequested(true))}
                        sideIcon={null}
                        data-attr="insight-ai-explain-button"
                        disabledReason={
                            insightDataLoading ? 'Please wait for the insight to finish loading' : undefined
                        }
                    >
                        Explain this insight
                    </LemonButton>
                </AIConsentPopoverWrapper>
            </div>
        </div>
    )
}
