import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { InsightShortId, SidePanelTab } from '~/types'

import { insightLogic } from './insightLogic'
import { insightVizDataLogic } from './insightVizDataLogic'

const EXPLAIN_PROMPT = '!Explain this insight'

export function InsightAIAnalysis(): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!insight.id) {
        return null
    }

    // An SSO reauth redirect unloads the page before the approval saves. On return the approval
    // finishes and this URL reopens the side panel with the prompt, so the click is not lost.
    const explainUrl = combineUrl(
        urls.insightView(insight.short_id as InsightShortId),
        {},
        { panel: `${SidePanelTab.Max}:${EXPLAIN_PROMPT}` }
    ).url

    return (
        <div className="mt-4 mb-4">
            <h2 className="font-semibold text-lg m-0 mb-2 flex items-center gap-2">PostHog AI</h2>
            <p className="text-muted mb-4">Open PostHog AI in the side panel and ask it what this insight shows.</p>
            <div className="flex gap-2 flex-wrap">
                <AIConsentPopoverWrapper
                    onApprove={() => openSidePanel(SidePanelTab.Max, EXPLAIN_PROMPT)}
                    pendingRedirectUrl={explainUrl}
                >
                    <LemonButton
                        type="secondary"
                        onClick={() => openSidePanel(SidePanelTab.Max, EXPLAIN_PROMPT)}
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
