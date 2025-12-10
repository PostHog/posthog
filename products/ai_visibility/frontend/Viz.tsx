import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconChevronRight, IconLogomark, IconMessage, IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTabs, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'

import { CompetitorComparison, MatrixCell, TopCitedSource, Topic } from './types'
import { DashboardTab, vizLogic } from './vizLogic'

export interface VizProps {
    brand: string
}

function TopBar({
    lastUpdated,
    onRefresh,
    isRefreshing,
}: {
    lastUpdated: string | null
    onRefresh: () => void
    isRefreshing: boolean
}): JSX.Element {
    const formattedDate = lastUpdated ? dayjs(lastUpdated).format('MMM D') : null

    return (
        <div className="flex items-center justify-between px-4 py-2 border-b bg-bg-light">
            <div className="flex items-center gap-2">
                <IconLogomark className="text-2xl" />
                <span className="font-semibold text-base">AI visibility</span>
            </div>
            <div className="flex items-center gap-3">
                {formattedDate && <span className="text-muted text-sm">Data last updated on {formattedDate}</span>}
                <LemonButton size="small" icon={<IconMessage />} type="secondary">
                    Feedback
                </LemonButton>
                <LemonButton
                    size="small"
                    icon={<IconRefresh />}
                    type="primary"
                    onClick={onRefresh}
                    loading={isRefreshing}
                >
                    Generate new report
                </LemonButton>
            </div>
        </div>
    )
}

function CategoryTag({ category }: { category: string }): JSX.Element {
    const colors: Record<string, 'primary' | 'highlight' | 'caution'> = {
        commercial: 'primary',
        informational: 'highlight',
        navigational: 'caution',
    }
    return <LemonTag type={colors[category] || 'default'}>{category}</LemonTag>
}

// Visibility bar component for topics table
function VisibilityBar({ value, max = 100 }: { value: number; max?: number }): JSX.Element {
    const percentage = Math.min(100, (value / max) * 100)
    const getColor = (pct: number): string => {
        if (pct >= 60) {
            return 'bg-success'
        }
        if (pct >= 30) {
            return 'bg-warning'
        }
        return 'bg-danger'
    }

    return (
        <div className="flex items-center gap-2">
            <div className="w-24 h-2 bg-border rounded-full overflow-hidden">
                <div
                    className={clsx('h-full rounded-full', getColor(percentage))}
                    style={{ width: `${percentage}%` }}
                />
            </div>
            <span className="text-sm font-medium w-10">{value}%</span>
        </div>
    )
}

// Ranking hero card
function RankingCard({
    rank,
    brandName,
    topCompetitors,
}: {
    rank: number
    brandName: string
    topCompetitors: { name: string; visibility: number }[]
}): JSX.Element {
    return (
        <div className="relative overflow-hidden rounded-lg bg-gradient-to-r from-[#1d4ed8] to-[#7c3aed] p-6 text-white">
            <div className="absolute right-0 top-0 h-full w-1/3 bg-gradient-to-l from-black/20 to-transparent" />
            <div className="relative z-10">
                <div className="flex items-baseline gap-1 mb-2">
                    <span className="text-5xl font-bold">#{rank}</span>
                    <span className="text-lg opacity-80">Most mentioned in your generated prompts</span>
                </div>
                <p className="text-sm opacity-80 mb-4">Login to PostHog to customize your prompts</p>
                <h3 className="text-xl font-semibold mb-3">Congratulations 🎉</h3>
                <div className="bg-black/30 rounded-lg p-4">
                    <div className="flex justify-between text-sm mb-2 opacity-80">
                        <span>Brand</span>
                        <span>% of AI responses that mention the brand</span>
                    </div>
                    {topCompetitors.slice(0, 3).map((comp, i) => (
                        <div key={comp.name} className="flex items-center justify-between py-2">
                            <div className="flex items-center gap-2">
                                <span className="text-lg">{i === 0 ? '🥇' : i === 1 ? '🥈' : '🥉'}</span>
                                <span className={comp.name === brandName ? 'font-bold' : ''}>{comp.name}</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <div className="w-48 h-2 bg-white/20 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-white/80 rounded-full"
                                        style={{ width: `${comp.visibility}%` }}
                                    />
                                </div>
                                <span className="w-12 text-right">{comp.visibility.toFixed(1)}%</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

// Competitor mentions bar chart
function CompetitorMentionsBar({
    brandName,
    visibilityScore,
    competitors,
}: {
    brandName: string
    visibilityScore: number
    competitors: { name: string; visibility: number }[]
}): JSX.Element {
    // Build full sorted list to get accurate rankings
    const fullList = [
        { name: brandName, visibility: visibilityScore, isOurBrand: true },
        ...competitors.map((c) => ({ ...c, isOurBrand: false })),
    ].sort((a, b) => b.visibility - a.visibility)

    // Add rank to each entry
    const rankedList = fullList.map((brand, index) => ({ ...brand, rank: index + 1 }))

    // Get top 9 competitors + our brand (with their true ranks)
    const ourBrand = rankedList.find((b) => b.isOurBrand)!
    const topCompetitors = rankedList.filter((b) => !b.isOurBrand).slice(0, 9)
    const displayList = [...topCompetitors, ourBrand].sort((a, b) => a.rank - b.rank)

    const maxVisibility = Math.max(...displayList.map((b) => b.visibility), 1)

    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">Competitor mentions vs {brandName}</h3>
                <Link to="#" className="text-xs text-primary">
                    View all
                </Link>
            </div>
            <div className="space-y-3">
                {displayList.map((brand) => (
                    <div key={brand.name} className="flex items-center gap-3">
                        <span
                            className={clsx(
                                'w-6 text-sm text-muted text-right',
                                brand.isOurBrand && 'text-[#f97316] font-semibold'
                            )}
                        >
                            {brand.rank}
                        </span>
                        <span className={clsx('w-28 text-sm truncate', brand.isOurBrand && 'font-semibold')}>
                            {brand.name}
                        </span>
                        <div className="flex-1 h-4 bg-border rounded overflow-hidden">
                            <div
                                className={clsx('h-full rounded', brand.isOurBrand ? 'bg-[#f97316]' : 'bg-gray-400')}
                                style={{ width: `${(brand.visibility / maxVisibility) * 100}%` }}
                            />
                        </div>
                        <span
                            className={clsx(
                                'w-10 text-sm text-right',
                                brand.isOurBrand ? 'text-[#f97316] font-semibold' : ''
                            )}
                        >
                            {brand.visibility}%
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}

// Top topics by visibility
function TopTopicsList({ topics }: { topics: Topic[] }): JSX.Element {
    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">Top topics by visibility</h3>
                <Link to="#" className="text-xs text-primary">
                    View all
                </Link>
            </div>
            <div className="space-y-3">
                {topics.slice(0, 5).map((topic) => (
                    <div key={topic.name} className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium">{topic.name}</p>
                            <p className="text-xs text-muted">
                                {topic.promptCount} mentions in {topic.prompts.length} responses
                            </p>
                        </div>
                        <VisibilityBar value={topic.visibility} />
                    </div>
                ))}
            </div>
        </div>
    )
}

// Top cited sources
function TopCitedSourcesList({ sources }: { sources: TopCitedSource[] }): JSX.Element {
    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">Top cited sources</h3>
                <Link to="#" className="text-xs text-primary">
                    View all
                </Link>
            </div>
            <div className="space-y-3">
                {sources.slice(0, 6).map((source) => (
                    <div key={source.domain} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <div className="w-5 h-5 rounded bg-border flex items-center justify-center text-xs">🌐</div>
                            <span className="text-sm">{source.domain}</span>
                        </div>
                        <span className="text-sm">
                            <strong>{source.responseCount}</strong> <span className="text-muted">responses</span>
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}

// Topics table with expandable rows
function TopicsTable({ topics }: { topics: Topic[] }): JSX.Element {
    const [expandedTopics, setExpandedTopics] = useState<Set<string>>(new Set())

    const toggleTopic = (name: string): void => {
        const newExpanded = new Set(expandedTopics)
        if (newExpanded.has(name)) {
            newExpanded.delete(name)
        } else {
            newExpanded.add(name)
        }
        setExpandedTopics(newExpanded)
    }

    return (
        <div className="border rounded-lg bg-bg-light">
            <div className="p-4 border-b">
                <h3 className="text-sm font-semibold">Topics</h3>
            </div>
            <table className="w-full">
                <thead>
                    <tr className="border-b text-left text-xs text-muted uppercase">
                        <th className="p-3">Topic</th>
                        <th className="p-3 text-right">Visibility</th>
                        <th className="p-3 text-right">Relevancy</th>
                        <th className="p-3 text-right">Avg rank</th>
                        <th className="p-3 text-right">Citations</th>
                    </tr>
                </thead>
                <tbody>
                    {topics.map((topic) => (
                        <>
                            <tr
                                key={topic.name}
                                className="border-b hover:bg-bg-300 cursor-pointer"
                                onClick={() => toggleTopic(topic.name)}
                            >
                                <td className="p-3">
                                    <div className="flex items-center gap-2">
                                        <IconChevronRight
                                            className={clsx(
                                                'w-4 h-4 transition-transform',
                                                expandedTopics.has(topic.name) && 'rotate-90'
                                            )}
                                        />
                                        <div>
                                            <p className="font-medium">{topic.name}</p>
                                            <p className="text-xs text-muted">{topic.promptCount} prompts</p>
                                        </div>
                                    </div>
                                </td>
                                <td className="p-3">
                                    <div className="flex justify-end">
                                        <div className="flex items-center gap-2">
                                            {topic.topCompetitors.slice(0, 4).map((c) => (
                                                <Tooltip key={c.name} title={c.name}>
                                                    <div className="w-5 h-5 rounded-full bg-border overflow-hidden flex items-center justify-center text-[10px]">
                                                        {c.icon ? (
                                                            <img
                                                                src={c.icon}
                                                                alt={c.name}
                                                                className="w-full h-full object-contain"
                                                            />
                                                        ) : (
                                                            c.name.charAt(0)
                                                        )}
                                                    </div>
                                                </Tooltip>
                                            ))}
                                            <VisibilityBar value={topic.visibility} />
                                        </div>
                                    </div>
                                </td>
                                <td className="p-3 text-right">{topic.relevancy}%</td>
                                <td className="p-3 text-right">
                                    {topic.avgRank > 0 ? `#${topic.avgRank.toFixed(1)}` : '-'}
                                </td>
                                <td className="p-3 text-right">{topic.citations}</td>
                            </tr>
                            {expandedTopics.has(topic.name) && (
                                <tr key={`${topic.name}-expanded`}>
                                    <td colSpan={5} className="bg-bg-300 p-4">
                                        <div className="space-y-2">
                                            {topic.prompts.map((prompt) => (
                                                <div
                                                    key={prompt.id}
                                                    className="flex items-center justify-between p-2 bg-bg-light rounded"
                                                >
                                                    <div className="flex items-center gap-2">
                                                        {prompt.you_mentioned ? (
                                                            <IconCheck className="w-4 h-4 text-success" />
                                                        ) : (
                                                            <IconX className="w-4 h-4 text-muted" />
                                                        )}
                                                        <span className="text-sm">{prompt.text}</span>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <CategoryTag category={prompt.category} />
                                                        {(prompt.competitors?.length
                                                            ? prompt.competitors.slice(0, 2)
                                                            : prompt.competitors_mentioned
                                                                  .slice(0, 2)
                                                                  .map((name) => ({ name, logo_url: undefined }))
                                                        ).map((comp) => (
                                                            <LemonTag key={comp.name} type="muted" size="small">
                                                                <span className="flex items-center gap-1">
                                                                    {comp.logo_url ? (
                                                                        <img
                                                                            src={comp.logo_url}
                                                                            alt={comp.name}
                                                                            className="w-4 h-4 rounded-full"
                                                                        />
                                                                    ) : (
                                                                        <span className="w-4 h-4 rounded-full bg-border flex items-center justify-center text-[10px]">
                                                                            {comp.name.charAt(0)}
                                                                        </span>
                                                                    )}
                                                                    <span>{comp.name}</span>
                                                                </span>
                                                            </LemonTag>
                                                        ))}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </td>
                                </tr>
                            )}
                        </>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

// Competitor comparison card
function ComparisonCard({
    comparison,
    brandName,
}: {
    comparison: CompetitorComparison
    brandName: string
}): JSX.Element {
    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">{brandName}</span>
                <span className="text-xs text-muted">vs</span>
                <span className="font-semibold">{comparison.competitor}</span>
            </div>
            <p className="text-sm text-muted mb-2">
                {brandName} appears higher in <span className="font-bold">{comparison.youLeadPercentage}%</span> of
                prompts
            </p>
            <p className="text-xs text-muted mb-3">{comparison.sharedPrompts} prompts analyzed</p>

            {/* Progress bar - brand percentage from left in blue */}
            <div className="flex h-3 rounded overflow-hidden mb-4 bg-gray-200">
                <div className="bg-[#3b82f6]" style={{ width: `${comparison.youLeadPercentage}%` }} />
            </div>

            <div className="space-y-1">
                {comparison.topicResults.map((result) => (
                    <div key={result.topic} className="flex justify-between text-xs">
                        <span className="text-muted">{result.topic}</span>
                        <span>{result.youPercentage}%</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

// Heatmap matrix
function CompetitorTopicsHeatmap({
    matrix,
    topics,
    competitors,
    brandName,
    visibilityScore,
}: {
    matrix: MatrixCell[]
    topics: Topic[]
    competitors: { name: string; visibility: number }[]
    brandName: string
    visibilityScore: number
}): JSX.Element {
    const [showRank, setShowRank] = useState(false)

    const getCell = (topicName: string, competitorName: string): MatrixCell | undefined => {
        return matrix.find((c) => c.topic === topicName && c.competitor === competitorName)
    }

    const getCellColor = (visibility: number): string => {
        if (visibility >= 70) {
            return 'bg-[#1e40af] text-white'
        }
        if (visibility >= 50) {
            return 'bg-[#3b82f6] text-white'
        }
        if (visibility >= 30) {
            return 'bg-[#93c5fd] text-gray-900'
        }
        if (visibility >= 10) {
            return 'bg-[#dbeafe] text-gray-700'
        }
        return 'bg-[#f1f5f9] text-gray-500'
    }

    const allCompetitors = [{ name: brandName, visibility: visibilityScore }, ...competitors]

    return (
        <div className="border rounded-lg bg-bg-light overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b">
                <h3 className="text-sm font-semibold">Competitors vs topics matrix</h3>
                <LemonSegmentedButton
                    size="small"
                    value={showRank ? 'rank' : 'visibility'}
                    onChange={(val) => setShowRank(val === 'rank')}
                    options={[
                        { value: 'visibility', label: 'Visibility percentage' },
                        { value: 'rank', label: 'Average rank' },
                    ]}
                />
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b">
                            <th className="p-3 text-left font-medium">Topic</th>
                            {allCompetitors.map((comp) => (
                                <th key={comp.name} className="p-3 text-center font-medium min-w-[80px]">
                                    <div className="flex flex-col items-center gap-1">
                                        <div className="w-6 h-6 rounded-full bg-border flex items-center justify-center text-xs">
                                            {comp.name.charAt(0)}
                                        </div>
                                        <span className="text-xs truncate max-w-[70px]">{comp.name}</span>
                                    </div>
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {topics.map((topic) => (
                            <tr key={topic.name} className="border-b">
                                <td className="p-3 font-medium">{topic.name}</td>
                                {allCompetitors.map((comp) => {
                                    const isBrand = comp.name === brandName
                                    const cellValue = isBrand
                                        ? topic.visibility
                                        : (getCell(topic.name, comp.name)?.visibility ?? 0)

                                    return (
                                        <td key={comp.name} className="p-1">
                                            <div
                                                className={clsx(
                                                    'p-2 text-center rounded text-xs font-medium',
                                                    getCellColor(cellValue)
                                                )}
                                            >
                                                {showRank
                                                    ? (() => {
                                                          const cell = getCell(topic.name, comp.name)
                                                          const rank = cell?.avgRank
                                                          return rank && rank > 0 ? `#${rank}` : '-'
                                                      })()
                                                    : `${cellValue}%`}
                                            </div>
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

// Overview tab content
function OverviewTab({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const { brandDisplayName, visibilityScore, brandRanking, topCompetitors, topics, topCitedSources } =
        useValues(logic)

    const rankingCompetitors = [{ name: brandDisplayName, visibility: visibilityScore }, ...topCompetitors].sort(
        (a, b) => b.visibility - a.visibility
    )

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <RankingCard rank={brandRanking} brandName={brandDisplayName} topCompetitors={rankingCompetitors} />
                <CompetitorMentionsBar
                    brandName={brandDisplayName}
                    visibilityScore={visibilityScore}
                    competitors={topCompetitors}
                />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <TopTopicsList topics={topics} />
                <TopCitedSourcesList sources={topCitedSources} />
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
                        ]}
                    />

                    {activeTab === 'overview' && <OverviewTab brand={brand} />}
                    {activeTab === 'prompts' && <PromptsTab brand={brand} />}
                    {activeTab === 'competitors' && <CompetitorsTab brand={brand} />}
                </div>
            </div>
        </div>
    )
}

export function Viz({ brand }: VizProps): JSX.Element {
    const logic = vizLogic({ brand: brand || 'posthog' })
    const { isReady, isPolling, triggerResultLoading, lastError, results, workflowId, brandDisplayName } =
        useValues(logic)
    const { loadTriggerResult } = useActions(logic)
    const [dotCount, setDotCount] = useState(1)
    const [lastUpdated, setLastUpdated] = useState<string | null>(null)

    useEffect(() => {
        if (!isPolling) {
            return
        }
        const interval = setInterval(() => {
            setDotCount((prev) => (prev % 3) + 1)
        }, 500)
        return () => clearInterval(interval)
    }, [isPolling])

    useEffect(() => {
        if (isReady && results) {
            setLastUpdated(new Date().toISOString())
        }
    }, [isReady, results])

    // Show dashboard when we have results
    if (isReady && results) {
        return <DashboardView brand={brand} lastUpdated={lastUpdated} />
    }

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
                    <div>
                        <h1 className="text-2xl font-bold mb-1">AI visibility for {brandDisplayName}</h1>
                        <p className="text-muted">Track how AI assistants mention your brand across prompts</p>
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
                        <div className="rounded border border-border bg-bg-light p-4">
                            <div className="flex items-center gap-2">
                                <Spinner />
                                <span>{isPolling ? `Processing${'.'.repeat(dotCount)}` : 'Starting analysis...'}</span>
                            </div>
                            {workflowId && (
                                <div className="mt-2 text-xs text-muted">
                                    Workflow ID: <span className="font-mono">{workflowId}</span>
                                </div>
                            )}
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    )
}
