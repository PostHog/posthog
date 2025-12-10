import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconLogomark } from '@posthog/icons'
import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'

import {
    ComparisonCard,
    CompetitorMentionsBar,
    CompetitorTopicsHeatmap,
    RankingCard,
    SourcesTable,
    TopBar,
    TopCitedSourcesList,
    TopTopicsList,
    TopicsTable,
} from './components'
import { DashboardTab, PROGRESS_STEPS, vizLogic } from './vizLogic'

export interface VizProps {
    brand: string
}

// Overview tab content
function OverviewTab({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const { brandDisplayName, visibilityScore, brandRanking, topCompetitors, topics, topCitedSources } =
        useValues(logic)
    const { setActiveTab } = useActions(logic)

    const rankingCompetitors = [
        { name: brandDisplayName, visibility: visibilityScore, domain: brand },
        ...topCompetitors,
    ].sort((a, b) => b.visibility - a.visibility)

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <RankingCard rank={brandRanking} brandName={brandDisplayName} topCompetitors={rankingCompetitors} />
                <CompetitorMentionsBar
                    brandName={brandDisplayName}
                    brandDomain={brand}
                    visibilityScore={visibilityScore}
                    competitors={topCompetitors}
                    onViewAll={() => setActiveTab('competitors')}
                />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <TopTopicsList topics={topics} onViewAll={() => setActiveTab('prompts')} />
                <TopCitedSourcesList sources={topCitedSources} onViewAll={() => setActiveTab('sources')} />
            </div>
        </div>
    )
}

// Prompts tab content
function PromptsTab({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const { topics, mentionStats } = useValues(logic)

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
                <div className="border rounded-lg p-4 bg-bg-light">
                    <p className="text-muted text-xs uppercase font-semibold">Topics</p>
                    <p className="text-2xl font-bold">{topics.length}</p>
                    <p className="text-xs text-muted">Topics related to your brand</p>
                </div>
                <div className="border rounded-lg p-4 bg-bg-light">
                    <p className="text-muted text-xs uppercase font-semibold">Prompts</p>
                    <p className="text-2xl font-bold">{mentionStats.total}</p>
                    <p className="text-xs text-muted">LLM prompts in all topics</p>
                </div>
                <div className="border rounded-lg p-4 bg-bg-light">
                    <p className="text-muted text-xs uppercase font-semibold">Responses</p>
                    <p className="text-2xl font-bold">{mentionStats.mentioned}</p>
                    <p className="text-xs text-muted">Responses from running prompts on LLMs</p>
                </div>
            </div>
            <TopicsTable topics={topics} />
        </div>
    )
}

// Competitors tab content
function CompetitorsTab({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const { brandDisplayName, visibilityScore, topCompetitors, topics, competitorComparisons, competitorTopicsMatrix } =
        useValues(logic)

    return (
        <div className="space-y-6">
            <CompetitorTopicsHeatmap
                matrix={competitorTopicsMatrix}
                topics={topics}
                competitors={topCompetitors}
                brandName={brandDisplayName}
                brandDomain={brand}
                visibilityScore={visibilityScore}
            />
            <div>
                <h3 className="text-lg font-semibold mb-4">Competitor comparisons</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {competitorComparisons.map((comparison) => (
                        <ComparisonCard
                            key={comparison.competitor}
                            comparison={comparison}
                            brandName={brandDisplayName}
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}

// Sources tab content
function SourcesTab({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const values = useValues(logic) as ReturnType<typeof useValues<typeof logic>> & {
        sourceDetails: { domain: string; pages: number; responses: number; brandMentionRate: number }[]
    }
    const { brandDisplayName } = values
    const sourceDetails = values.sourceDetails ?? []

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
                <div className="border rounded-lg p-4 bg-bg-light">
                    <p className="text-muted text-xs uppercase font-semibold">Total sources</p>
                    <p className="text-2xl font-bold">{sourceDetails.length}</p>
                    <p className="text-xs text-muted">Unique domains cited by AI</p>
                </div>
                <div className="border rounded-lg p-4 bg-bg-light">
                    <p className="text-muted text-xs uppercase font-semibold">Sources mentioning {brandDisplayName}</p>
                    <p className="text-2xl font-bold">{sourceDetails.filter((s) => s.brandMentionRate > 0).length}</p>
                    <p className="text-xs text-muted">Sources that mention your brand</p>
                </div>
            </div>

            <SourcesTable sources={sourceDetails} brandName={brandDisplayName} />
        </div>
    )
}

function DashboardView({ brand, lastUpdated }: { brand: string; lastUpdated: string | null }): JSX.Element {
    const logic = vizLogic({ brand })
    const { activeTab, triggerResultLoading } = useValues(logic)
    const { setActiveTab, forceNewRun } = useActions(logic)

    return (
        <div className="flex flex-col h-full">
            <TopBar lastUpdated={lastUpdated} onRefresh={forceNewRun} isRefreshing={triggerResultLoading} />
            <div className="flex-1 overflow-auto">
                <div className="p-6 space-y-6 max-w-7xl mx-auto">
                    <div>
                        <h1 className="text-4xl font-bold mb-1 flex items-center gap-2">
                            <img
                                src={`https://www.google.com/s2/favicons?domain=${brand}&sz=128`}
                                alt=""
                                className="w-6 h-6"
                            />
                            {brand}
                        </h1>
                        <p className="text-muted text-lg">Track how AI assistants mention your brand across prompts</p>
                    </div>

                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as DashboardTab)}
                        tabs={[
                            { key: 'overview', label: 'Overview' },
                            { key: 'prompts', label: 'Prompts' },
                            { key: 'competitors', label: 'Competitors' },
                            { key: 'sources', label: 'Sources' },
                        ]}
                    />

                    {activeTab === 'overview' && <OverviewTab brand={brand} />}
                    {activeTab === 'prompts' && <PromptsTab brand={brand} />}
                    {activeTab === 'competitors' && <CompetitorsTab brand={brand} />}
                    {activeTab === 'sources' && <SourcesTab brand={brand} />}
                </div>
            </div>
        </div>
    )
}

export function Viz({ brand }: VizProps): JSX.Element {
    const logic = vizLogic({ brand: brand || 'posthog' })
    const {
        isReady,
        isPolling,
        triggerResultLoading,
        triggerResult,
        lastError,
        results,
        brandDisplayName,
        progressStep,
        progressPercent,
        progressLabel,
    } = useValues(logic) as ReturnType<typeof useValues<typeof logic>> & {
        progressStep: string
        progressPercent: number
        progressLabel: string
    }
    const { loadTriggerResult } = useActions(logic)
    const [lastUpdated, setLastUpdated] = useState<string | null>(null)

    useEffect(() => {
        if (isReady && results) {
            setLastUpdated(new Date().toISOString())
        }
    }, [isReady, results])

    // Show dashboard when we have results
    if (isReady && results) {
        return <DashboardView brand={brand} lastUpdated={lastUpdated} />
    }

    // Initial loading state - checking database for existing report
    const isInitialLoad = triggerResultLoading && triggerResult === null && !isPolling

    const currentStepIndex = PROGRESS_STEPS.findIndex((s) => s.step === progressStep)

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center px-4 py-2 border-b bg-bg-light">
                <div className="flex items-center gap-2">
                    <IconLogomark className="text-2xl" />
                    <span className="font-semibold text-base">AI visibility</span>
                </div>
            </div>
            <div className="flex-1 overflow-auto">
                <div className="p-6 max-w-2xl mx-auto space-y-4">
                    {isInitialLoad ? (
                        <div className="flex flex-col items-center justify-center py-12 space-y-4">
                            <Spinner className="text-4xl" />
                            <div className="text-center">
                                <h2 className="text-lg font-semibold">Checking for existing report...</h2>
                                <p className="text-muted text-sm">Looking up {brandDisplayName} in our database</p>
                            </div>
                        </div>
                    ) : (
                        <>
                            <div>
                                <h1 className="text-2xl font-bold mb-1">Generating report for {brandDisplayName}...</h1>
                            </div>

                            {lastError ? (
                                <div className="rounded border border-border bg-bg-light p-4">
                                    <div className="flex flex-col gap-2">
                                        <span className="text-danger font-semibold">Failed to load results</span>
                                        <code className="text-xs break-all">{lastError}</code>
                                        <LemonButton type="primary" onClick={() => loadTriggerResult()}>
                                            Retry
                                        </LemonButton>
                                    </div>
                                </div>
                            ) : triggerResultLoading || isPolling ? (
                                <div className="rounded border border-border bg-bg-light p-4 space-y-4">
                                    {/* Progress bar */}
                                    <div>
                                        <div className="flex items-center justify-between mb-2">
                                            <div className="flex items-center gap-2">
                                                <Spinner className="text-sm" />
                                                <span className="font-medium">{progressLabel}</span>
                                            </div>
                                            <span className="text-sm text-muted">{progressPercent}%</span>
                                        </div>
                                        <div className="h-2 bg-border rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-primary transition-all duration-500 ease-out rounded-full"
                                                // eslint-disable-next-line react/forbid-dom-props
                                                style={{ width: `${progressPercent}%` }}
                                            />
                                        </div>
                                    </div>

                                    {/* Step indicators */}
                                    <div className="space-y-1">
                                        {PROGRESS_STEPS.filter((s) => s.step !== 'complete').map((step, idx) => {
                                            const isComplete = idx < currentStepIndex
                                            const isCurrent = idx === currentStepIndex
                                            return (
                                                <div
                                                    key={step.step}
                                                    className={`flex items-center gap-2 text-sm ${
                                                        isComplete
                                                            ? 'text-success'
                                                            : isCurrent
                                                              ? 'text-default font-medium'
                                                              : 'text-muted'
                                                    }`}
                                                >
                                                    <span className="w-4 text-center">
                                                        {isComplete ? '✓' : isCurrent ? '→' : '○'}
                                                    </span>
                                                    <span>{step.label}</span>
                                                </div>
                                            )
                                        })}
                                    </div>
                                </div>
                            ) : null}
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
