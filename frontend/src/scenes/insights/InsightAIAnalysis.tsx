import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { insightLogic } from './insightLogic'
import { insightVizDataLogic } from './insightVizDataLogic'

export function InsightAIAnalysis(): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!insight.id) {
        return null
    }

    return (
        <div className="mt-4 mb-4">
            <h2 className="font-semibold text-lg m-0 mb-2 flex items-center gap-2">AI analysis</h2>
            <p className="text-muted mb-4">
                Get AI-powered insights about your data, including trends, patterns, and actionable recommendations.
            </p>
            <div className="flex gap-2 flex-wrap">
                <AIConsentPopoverWrapper onApprove={() => openSidePanel(SidePanelTab.Max, '!Explain this insight')}>
                    <LemonButton
                        type="secondary"
                        onClick={() => openSidePanel(SidePanelTab.Max, '!Explain this insight')}
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
