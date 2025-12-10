import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import api from '~/lib/api'
import { InsightQueryNode } from '~/queries/schema/schema-general'

import { InsightDiveDeeperSection } from './InsightDiveDeeperSection'
import { insightLogic } from './insightLogic'
import { insightVizDataLogic } from './insightVizDataLogic'

export interface InsightAIAnalysisProps {
    query: InsightQueryNode
}

export function InsightAIAnalysis({ query }: InsightAIAnalysisProps): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const [analysis, setAnalysis] = useState<string | null>(null)
    const [isAnalyzing, setIsAnalyzing] = useState(false)
    const [hasClickedAnalyze, setHasClickedAnalyze] = useState(false)

    useEffect(() => {
        // Reset analysis when insight changes
        setAnalysis(null)
        setHasClickedAnalyze(false)
    }, [insight.id, JSON.stringify(query)])

    const handleAnalyze = async (): Promise<void> => {
        if (!insight.id || insightDataLoading) {
            return
        }

        setHasClickedAnalyze(true)
        setIsAnalyzing(true)

        try {
            const response = await api.insights.analyze(insight.id)
            setAnalysis(response.result)
        } catch (e) {
            console.error('[InsightAIAnalysis] Error fetching analysis', e)
            setAnalysis(null)
        } finally {
            setIsAnalyzing(false)
        }
    }

    if (!insight.id) {
        return null
    }

    return (
        <div className="mt-4">
            <h2 className="font-semibold text-lg m-0 mb-2">AI analysis</h2>

            {!hasClickedAnalyze ? (
                <>
                    <p className="text-muted mb-4">
                        Get AI-powered insights about your data, including trends, patterns, and actionable
                        recommendations
                    </p>
                    <LemonButton
                        type="primary"
                        onClick={handleAnalyze}
                        loading={isAnalyzing}
                        disabledReason={
                            insightDataLoading ? 'Please wait for the insight to finish loading' : undefined
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
                    </div>
                    <InsightDiveDeeperSection query={query} analysisContext={analysis} />
                </>
            ) : (
                <div className="text-muted">Failed to generate analysis. Please try again.</div>
            )}
        </div>
    )
}
