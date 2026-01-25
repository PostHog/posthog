import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { billingLogic } from 'scenes/billing/billingLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { BillingPlan } from '~/types'

import { InsightSuggestions } from './InsightSuggestions'
import { insightAIAnalysisLogic } from './insightAIAnalysisLogic'
import { insightLogic } from './insightLogic'
import { insightVizDataLogic } from './insightVizDataLogic'

export interface InsightAIAnalysisProps {
    query: InsightQueryNode
}

export function InsightAIAnalysis({ query }: InsightAIAnalysisProps): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { currentPlatformAddon, billingLoading } = useValues(billingLogic)
    const { analysis, isAnalyzing, hasClickedAnalyze, analysisFeedbackGiven } = useValues(
        insightAIAnalysisLogic({ insightId: insight.id, query })
    )
    const { startAnalysis, resetAnalysis, reportAnalysisFeedback } = useActions(
        insightAIAnalysisLogic({ insightId: insight.id, query })
    )

    // Check for at least Boost add-on (Boost, Scale, or Enterprise)
    const hasBoostOrHigher =
        currentPlatformAddon?.type === BillingPlan.Boost ||
        currentPlatformAddon?.type === BillingPlan.Scale ||
        currentPlatformAddon?.type === BillingPlan.Enterprise

    useEffect(() => {
        // Reset analysis when insight changes
        resetAnalysis()
    }, [insight.id, JSON.stringify(query), resetAnalysis])

    if (!insight.id) {
        return null
    }

    return (
        <div className="mt-4 mb-4">
            <h2 className="font-semibold text-lg m-0 mb-2">AI analysis</h2>

            {!hasClickedAnalyze ? (
                <>
                    <p className="text-muted mb-4">
                        Get AI-powered insights about your data, including trends, patterns, and actionable
                        recommendations. Find similar insights and get suggestions for next steps.
                    </p>
                    <LemonButton
                        type="primary"
                        onClick={startAnalysis}
                        loading={isAnalyzing}
                        disabledReason={
                            billingLoading
                                ? 'Loading billing information...'
                                : !hasBoostOrHigher
                                  ? 'Upgrade to at least the Boost add-on to use AI analysis'
                                  : insightDataLoading
                                    ? 'Please wait for the insight to finish loading'
                                    : undefined
                        }
                    >
                        Analyze with AI
                    </LemonButton>
                </>
            ) : isAnalyzing ? (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner className="text-xl" />
                    <span>Analyzing your insight...</span>
                </div>
            ) : analysis ? (
                <>
                    <div className="bg-surface-secondary border border-border rounded p-4 mb-4 whitespace-pre-wrap">
                        {analysis}
                        <div className="flex gap-2 justify-end mt-4 border-t border-border pt-2">
                            <span className="text-muted text-xs flex items-center">
                                {analysisFeedbackGiven !== null
                                    ? 'Thanks for your feedback!'
                                    : 'Was this analysis helpful?'}
                            </span>
                            <LemonButton
                                size="small"
                                icon={<IconThumbsUp />}
                                onClick={() => reportAnalysisFeedback(true)}
                                tooltip="Helpful"
                                disabled={analysisFeedbackGiven !== null}
                                active={analysisFeedbackGiven === true}
                            />
                            <LemonButton
                                size="small"
                                icon={<IconThumbsDown />}
                                onClick={() => reportAnalysisFeedback(false)}
                                tooltip="Not helpful"
                                disabled={analysisFeedbackGiven !== null}
                                active={analysisFeedbackGiven === false}
                            />
                        </div>
                    </div>
                    <InsightSuggestions insightId={insight.id} query={query} />
                </>
            ) : (
                <div className="text-muted">Failed to generate analysis. Please try again.</div>
            )}
        </div>
    )
}
