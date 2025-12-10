import 'chartjs-adapter-dayjs-3'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck, IconTrending, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonSegmentedButton,
    LemonTable,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { ChartDataset, ChartOptions } from 'lib/Chart'
import { getSeriesColor } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'

import { Results } from './Results'
import { PlatformMention, Prompt } from './types'
import { vizLogic } from './vizLogic'

export interface VizProps {
    brand: string
}

function WorkflowTriggerView({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const { loadTriggerResult } = useActions(logic)
    const { workflowId, triggerResultLoading, lastError, isReady, results, runId, brandDisplayName } = useValues(logic)

    return (
        <div className="flex flex-col gap-3 p-4 max-w-2xl mx-auto">
            <div>
                <h2 className="text-lg font-semibold">AI Visibility</h2>
                <p className="text-sm text-muted">
                    Starting workflow for: <span className="font-mono">{brandDisplayName}</span>
                </p>
            </div>

            {lastError ? (
                <div className="rounded border border-border bg-bg-300 p-3">
                    <div className="flex flex-col gap-2">
                        <span className="text-danger font-semibold">Failed to load results</span>
                        <code className="text-xs break-all">{lastError}</code>
                        <LemonButton type="primary" onClick={() => loadTriggerResult()}>
                            Retry
                        </LemonButton>
                    </div>
                </div>
            ) : isReady && results ? (
                <Results results={results} domain={brand} runId={runId} />
            ) : (
                <div className="rounded border border-border bg-bg-300 p-3">
                    <div className="flex items-center gap-2">
                        <Spinner />
                        <span>
                            {triggerResultLoading && !workflowId
                                ? 'Starting workflow...'
                                : 'Processing... checking again in 5 seconds'}
                        </span>
                    </div>
                    {workflowId && (
                        <div className="mt-2 text-xs text-muted">
                            Workflow ID: <span className="font-mono">{workflowId}</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

function ScoreCard({
    title,
    value,
    subtitle,
    trend,
    trendValue,
}: {
    title: string
    value: string | number
    subtitle?: string
    trend?: 'up' | 'down' | 'flat'
    trendValue?: string
}): JSX.Element {
    const TrendIcon = trend === 'up' ? IconTrending : trend === 'down' ? IconTrendingDown : IconTrendingFlat
    const trendColor = trend === 'up' ? 'text-success' : trend === 'down' ? 'text-danger' : 'text-muted'

    return (
        <div className="border rounded-lg p-4 bg-bg-light flex flex-col">
            <span className="text-muted text-xs uppercase font-semibold tracking-wide">{title}</span>
            <div className="flex items-baseline gap-2 mt-1">
                <span className="text-3xl font-bold">{value}</span>
                {trend && trendValue && (
                    <span className={clsx('flex items-center gap-1 text-sm', trendColor)}>
                        <TrendIcon className="w-4 h-4" />
                        {trendValue}
                    </span>
                )}
            </div>
            {subtitle && <span className="text-muted text-xs mt-1">{subtitle}</span>}
        </div>
    )
}

function ShareOfVoiceBar({ data }: { data: { name: string; value: number }[] }): JSX.Element {
    const total = data.reduce((sum, d) => sum + d.value, 0)

    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <h3 className="text-sm font-semibold mb-3">Share of voice</h3>
            <div className="flex h-8 rounded overflow-hidden mb-3">
                {data.map((item, i) => (
                    <Tooltip key={item.name} title={`${item.name}: ${(item.value * 100).toFixed(0)}%`}>
                        <div
                            className="h-full transition-all"
                            style={{
                                width: `${(item.value / total) * 100}%`,
                                backgroundColor: getSeriesColor(i),
                            }}
                        />
                    </Tooltip>
                ))}
            </div>
            <div className="flex flex-wrap gap-3">
                {data.map((item, i) => (
                    <div key={item.name} className="flex items-center gap-1.5 text-xs">
                        <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: getSeriesColor(i) }} />
                        <span className="font-medium">{item.name}</span>
                        <span className="text-muted">{(item.value * 100).toFixed(0)}%</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function MentionRateChart({
    dates,
    series,
}: {
    dates: string[]
    series: { id: number; label: string; data: number[]; dates: string[] }[]
}): JSX.Element {
    const { canvasRef } = useChart<'line'>({
        getConfig: () => {
            const datasets: ChartDataset<'line'>[] = series.map((s) => ({
                label: s.label,
                data: s.data,
                borderColor: getSeriesColor(s.id),
                backgroundColor: getSeriesColor(s.id),
                borderWidth: s.id === 0 ? 3 : 2,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 4,
            }))

            const options: ChartOptions<'line'> = {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'day', displayFormats: { day: 'MMM DD' } },
                        grid: { display: false },
                    },
                    y: {
                        beginAtZero: true,
                        max: 50,
                        ticks: { callback: (v) => `${v}%` },
                    },
                },
                plugins: {
                    legend: { display: true, position: 'bottom', labels: { usePointStyle: true, boxWidth: 6 } },
                    // @ts-expect-error Types out of date
                    crosshair: false,
                },
            }

            return { type: 'line' as const, data: { labels: dates, datasets }, options }
        },
        deps: [dates, series],
    })

    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <h3 className="text-sm font-semibold mb-3">Mention rate over time</h3>
            <div className="h-64">
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}

function PlatformCell({ platform }: { platform: PlatformMention | undefined }): JSX.Element {
    if (!platform?.mentioned) {
        return (
            <span className="text-muted">
                <IconX className="w-4 h-4" />
            </span>
        )
    }

    return (
        <div className="flex items-center gap-1">
            <LemonBadge status="success" size="small" content={String(platform.position || '?')} />
            {platform.cited && (
                <Tooltip title="Cited with link">
                    <span className="text-success">
                        <IconCheck className="w-3 h-3" />
                    </span>
                </Tooltip>
            )}
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

function PromptsTable({
    prompts,
    filterCategory,
    onFilterChange,
}: {
    prompts: Prompt[]
    filterCategory: 'all' | 'commercial' | 'informational' | 'navigational'
    onFilterChange: (cat: 'all' | 'commercial' | 'informational' | 'navigational') => void
}): JSX.Element {
    const columns: LemonTableColumns<Prompt> = [
        {
            title: 'Prompt',
            dataIndex: 'text' as const,
            key: 'text',
            render: (_: unknown, prompt: Prompt) => (
                <div className="flex flex-col gap-1">
                    <span className="font-medium">{prompt.text}</span>
                    <div className="flex items-center gap-2">
                        <CategoryTag category={prompt.category} />
                        {prompt.you_mentioned ? (
                            <LemonTag type="success">Mentioned</LemonTag>
                        ) : (
                            <LemonTag type="muted">Not mentioned</LemonTag>
                        )}
                    </div>
                </div>
            ),
        },
        {
            title: 'ChatGPT',
            key: 'chatgpt',
            render: (_: unknown, prompt: Prompt) => <PlatformCell platform={prompt.platforms.chatgpt} />,
            align: 'center' as const,
        },
        {
            title: 'Perplexity',
            key: 'perplexity',
            render: (_: unknown, prompt: Prompt) => <PlatformCell platform={prompt.platforms.perplexity} />,
            align: 'center' as const,
        },
        {
            title: 'Gemini',
            key: 'gemini',
            render: (_: unknown, prompt: Prompt) => <PlatformCell platform={prompt.platforms.gemini} />,
            align: 'center' as const,
        },
        {
            title: 'Claude',
            key: 'claude',
            render: (_: unknown, prompt: Prompt) => <PlatformCell platform={prompt.platforms.claude} />,
            align: 'center' as const,
        },
        {
            title: 'Competitors',
            key: 'competitors',
            render: (_: unknown, prompt: Prompt) => (
                <div className="flex flex-wrap gap-1 max-w-48">
                    {prompt.competitors_mentioned.slice(0, 3).map((c) => (
                        <LemonTag key={c} type="muted" size="small">
                            {c}
                        </LemonTag>
                    ))}
                    {prompt.competitors_mentioned.length > 3 && (
                        <span className="text-muted text-xs">+{prompt.competitors_mentioned.length - 3}</span>
                    )}
                </div>
            ),
        },
    ]

    return (
        <div className="border rounded-lg bg-bg-light">
            <div className="flex items-center justify-between p-4 border-b">
                <h3 className="text-sm font-semibold">Tracked prompts</h3>
                <LemonSegmentedButton
                    size="small"
                    value={filterCategory}
                    onChange={onFilterChange}
                    options={[
                        { value: 'all', label: 'All' },
                        { value: 'commercial', label: 'Commercial' },
                        { value: 'informational', label: 'Informational' },
                    ]}
                />
            </div>
            <LemonTable dataSource={prompts} columns={columns} rowKey="id" size="small" />
        </div>
    )
}

function DashboardView({ brand }: { brand: string }): JSX.Element {
    const logic = vizLogic({ brand })
    const {
        brandDisplayName,
        visibilityScore,
        scoreChange,
        scoreChangePeriod,
        shareOfVoiceChartData,
        chartData,
        filteredPrompts,
        filterCategory,
        mentionStats,
        availableBrands,
    } = useValues(logic)
    const { setFilterCategory } = useActions(logic)

    return (
        <div className="p-6 space-y-6 max-w-7xl mx-auto">
            <div className="flex items-start justify-between">
                <div>
                    <h1 className="text-2xl font-bold mb-1">AI visibility for {brandDisplayName}</h1>
                    <p className="text-muted">Track how AI assistants mention your brand across prompts</p>
                </div>
                <div className="flex gap-2">
                    {availableBrands.map((b: string) => (
                        <Link
                            key={b}
                            to={`/viz/${b}`}
                            className={clsx(
                                'px-3 py-1.5 rounded text-sm font-medium transition-colors',
                                b === brand
                                    ? 'bg-primary text-primary-inverse'
                                    : 'bg-bg-light hover:bg-border text-default'
                            )}
                        >
                            {b.charAt(0).toUpperCase() + b.slice(1)}
                        </Link>
                    ))}
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <ScoreCard
                    title="Visibility score"
                    value={visibilityScore}
                    subtitle="Overall AI visibility rating"
                    trend={scoreChange > 0 ? 'up' : scoreChange < 0 ? 'down' : 'flat'}
                    trendValue={`${scoreChange > 0 ? '+' : ''}${scoreChange} this ${scoreChangePeriod}`}
                />
                <ScoreCard
                    title="Prompts tracked"
                    value={mentionStats.total}
                    subtitle={`${mentionStats.mentioned} with mentions`}
                />
                <ScoreCard title="Top position" value={mentionStats.topPosition} subtitle="Prompts where you rank #1" />
                <ScoreCard title="Citations" value={mentionStats.cited} subtitle="Prompts with source links" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <ShareOfVoiceBar data={shareOfVoiceChartData} />
                <MentionRateChart dates={chartData.dates} series={chartData.series} />
            </div>

            <PromptsTable
                prompts={filteredPrompts}
                filterCategory={filterCategory}
                onFilterChange={setFilterCategory}
            />
        </div>
    )
}

export function Viz({ brand }: VizProps): JSX.Element {
    const logic = vizLogic({ brand: brand || 'posthog' })
    const { hasMockData } = useValues(logic)

    // Mock data brands get the full dashboard, others get the workflow trigger view
    return hasMockData ? <DashboardView brand={brand} /> : <WorkflowTriggerView brand={brand} />
}
