import { useValues } from 'kea'
import { useCallback, useState } from 'react'

import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { DebugCHQueries } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { runWithLimit } from 'scenes/dashboard/dashboardUtils'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    ExperimentQueryResponse,
    ExperimentStatsBaseValidated,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    NewExperimentQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import { experimentLogic, ExperimentSavedMetric } from '../experimentLogic'
import { getExperimentRefreshMode } from '../metricQueryUtils'
import { getDefaultMetricTitle } from '../MetricsView/shared/utils'

const COMPARISON_CONCURRENCY_LIMIT = 10

interface PathResult {
    response: ExperimentQueryResponse | null
    durationMs: number | null
    error: string | null
    loading: boolean
}

const EMPTY_PATH_RESULT: PathResult = { response: null, durationMs: null, error: null, loading: false }

interface ComparisonRow {
    variant: string
    directCount: number | null
    precomputedCount: number | null
    directSum: number | null
    precomputedSum: number | null
    directMean: number | null
    precomputedMean: number | null
    match: boolean | null
}

function isNewResponse(response: ExperimentQueryResponse): response is NewExperimentQueryResponse {
    return 'baseline' in response && response.baseline !== null
}

function buildComparisonRows(direct: ExperimentQueryResponse, precomputed: ExperimentQueryResponse): ComparisonRow[] {
    if (!isNewResponse(direct) || !isNewResponse(precomputed)) {
        return []
    }

    const rows: ComparisonRow[] = []

    const directBaseline = direct.baseline
    const precomputedBaseline = precomputed.baseline
    if (directBaseline && precomputedBaseline) {
        rows.push(buildRow(directBaseline, precomputedBaseline))
    }

    const directVariants = direct.variant_results || []
    const precomputedVariants = precomputed.variant_results || []

    for (const dv of directVariants) {
        const pv = precomputedVariants.find((v) => v.key === dv.key)
        rows.push(buildRow(dv, pv ?? null))
    }

    return rows
}

function buildRow(
    direct: ExperimentStatsBaseValidated,
    precomputed: ExperimentStatsBaseValidated | null
): ComparisonRow {
    return {
        variant: direct.key,
        directCount: direct.number_of_samples,
        precomputedCount: precomputed?.number_of_samples ?? null,
        directSum: direct.sum,
        precomputedSum: precomputed?.sum ?? null,
        directMean: getMean(direct),
        precomputedMean: precomputed ? getMean(precomputed) : null,
        match:
            precomputed != null
                ? direct.number_of_samples === precomputed.number_of_samples && direct.sum === precomputed.sum
                : null,
    }
}

function getMean(stats: ExperimentStatsBaseValidated): number | null {
    if (stats.number_of_samples === 0) {
        return null
    }
    return stats.sum / stats.number_of_samples
}

function getSignificance(
    response: ExperimentQueryResponse
): { significant: boolean; pValue?: number; chanceToWin?: number } | null {
    if (!isNewResponse(response)) {
        return null
    }
    const firstVariant = response.variant_results?.[0]
    if (!firstVariant) {
        return null
    }
    if ('p_value' in firstVariant) {
        const v = firstVariant as ExperimentVariantResultFrequentist
        return { significant: !!v.significant, pValue: v.p_value }
    }
    if ('chance_to_win' in firstVariant) {
        const v = firstVariant as ExperimentVariantResultBayesian
        return { significant: !!v.significant, chanceToWin: v.chance_to_win }
    }
    return null
}

async function runPathQuery(
    metric: ExperimentMetric,
    experimentId: number,
    mode: 'direct' | 'precomputed',
    featureFlags: Record<string, boolean | string>
): Promise<PathResult> {
    const query = {
        kind: NodeKind.ExperimentQuery as const,
        metric,
        experiment_id: experimentId,
        precomputation_mode: mode,
    }
    const startTime = performance.now()
    try {
        const response = await performQuery(
            setLatestVersionsOnQuery(query),
            undefined,
            getExperimentRefreshMode(featureFlags, true)
        )
        return {
            response: response as ExperimentQueryResponse,
            durationMs: Math.round(performance.now() - startTime),
            error: null,
            loading: false,
        }
    } catch (e: any) {
        return {
            response: null,
            durationMs: Math.round(performance.now() - startTime),
            error: e?.message || 'Unknown error',
            loading: false,
        }
    }
}

function MetricComparisonResults({
    direct,
    precomputed,
}: {
    direct: PathResult
    precomputed: PathResult
}): JSX.Element | null {
    if (!direct.loading && !direct.response && !direct.error) {
        return null
    }

    const hasResults = direct.response && precomputed.response
    const comparisonRows = hasResults ? buildComparisonRows(direct.response!, precomputed.response!) : []
    const directSig = direct.response ? getSignificance(direct.response) : null
    const precomputedSig = precomputed.response ? getSignificance(precomputed.response) : null

    const columns: LemonTableColumns<ComparisonRow> = [
        {
            title: 'Variant',
            dataIndex: 'variant',
            key: 'variant',
        },
        {
            title: 'Direct count',
            key: 'directCount',
            render: (_, row) => row.directCount ?? '—',
        },
        {
            title: 'Precomputed count',
            key: 'precomputedCount',
            render: (_, row) => row.precomputedCount ?? '—',
        },
        {
            title: 'Direct mean',
            key: 'directMean',
            render: (_, row) => (row.directMean != null ? row.directMean.toFixed(4) : '—'),
        },
        {
            title: 'Precomputed mean',
            key: 'precomputedMean',
            render: (_, row) => (row.precomputedMean != null ? row.precomputedMean.toFixed(4) : '—'),
        },
        {
            title: 'Match',
            key: 'match',
            render: (_, row) =>
                row.match === null ? (
                    '—'
                ) : row.match ? (
                    <LemonTag type="success">Yes</LemonTag>
                ) : (
                    <LemonTag type="danger">No</LemonTag>
                ),
        },
    ]

    return (
        <div className="mt-2">
            <div className="flex gap-4 mb-2">
                <div className="flex items-center gap-1">
                    <span className="text-muted">Direct:</span>
                    {direct.loading ? (
                        <Spinner />
                    ) : direct.error ? (
                        <LemonTag type="danger">Error</LemonTag>
                    ) : (
                        <LemonTag type="default">{direct.durationMs}ms</LemonTag>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    <span className="text-muted">Precomputed:</span>
                    {precomputed.loading ? (
                        <Spinner />
                    ) : precomputed.error ? (
                        <LemonTag type="danger">Error</LemonTag>
                    ) : (
                        <LemonTag type="default">{precomputed.durationMs}ms</LemonTag>
                    )}
                </div>
                {direct.durationMs && precomputed.durationMs && (
                    <div className="flex items-center gap-1">
                        <span className="text-muted">Speedup:</span>
                        <LemonTag type={precomputed.durationMs < direct.durationMs ? 'success' : 'warning'}>
                            {(direct.durationMs / precomputed.durationMs).toFixed(2)}x
                        </LemonTag>
                    </div>
                )}
            </div>

            {directSig && precomputedSig && (
                <div className="flex gap-4 mb-2">
                    <div className="flex items-center gap-1">
                        <span className="text-muted">Direct significant:</span>
                        <LemonTag type={directSig.significant ? 'success' : 'default'}>
                            {directSig.significant ? 'Yes' : 'No'}
                            {directSig.pValue != null ? ` (p=${directSig.pValue.toFixed(4)})` : ''}
                            {directSig.chanceToWin != null ? ` (${(directSig.chanceToWin * 100).toFixed(1)}%)` : ''}
                        </LemonTag>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-muted">Precomputed significant:</span>
                        <LemonTag type={precomputedSig.significant ? 'success' : 'default'}>
                            {precomputedSig.significant ? 'Yes' : 'No'}
                            {precomputedSig.pValue != null ? ` (p=${precomputedSig.pValue.toFixed(4)})` : ''}
                            {precomputedSig.chanceToWin != null
                                ? ` (${(precomputedSig.chanceToWin * 100).toFixed(1)}%)`
                                : ''}
                        </LemonTag>
                    </div>
                </div>
            )}

            {direct.error && <div className="text-danger text-sm mb-1">Direct error: {direct.error}</div>}
            {precomputed.error && (
                <div className="text-danger text-sm mb-1">Precomputed error: {precomputed.error}</div>
            )}

            {comparisonRows.length > 0 && <LemonTable dataSource={comparisonRows} columns={columns} size="small" />}
        </div>
    )
}

interface MetricEntry {
    metric: ExperimentMetric
    isPrimary: boolean
    index: number
}

function ExperimentExecutionPathComparison({ experimentId }: { experimentId: number }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [results, setResults] = useState<Record<string, { direct: PathResult; precomputed: PathResult }>>({})
    const [runAllInProgress, setRunAllInProgress] = useState(false)

    const sharedPrimaryMetrics: ExperimentMetric[] =
        (experiment.saved_metrics as ExperimentSavedMetric[] | undefined)
            ?.filter(({ metadata }) => metadata.type === 'primary')
            .map(({ query }) => query) ?? []

    const sharedSecondaryMetrics: ExperimentMetric[] =
        (experiment.saved_metrics as ExperimentSavedMetric[] | undefined)
            ?.filter(({ metadata }) => metadata.type === 'secondary')
            .map(({ query }) => query) ?? []

    const primaryMetrics = [...(experiment.metrics || []), ...sharedPrimaryMetrics].filter(
        (m): m is ExperimentMetric => m.kind === NodeKind.ExperimentMetric
    )
    const secondaryMetrics = [...(experiment.metrics_secondary || []), ...sharedSecondaryMetrics].filter(
        (m): m is ExperimentMetric => m.kind === NodeKind.ExperimentMetric
    )

    const allMetrics: MetricEntry[] = [
        ...primaryMetrics.map((metric, i) => ({ metric, isPrimary: true, index: i })),
        ...secondaryMetrics.map((metric, i) => ({ metric, isPrimary: false, index: i })),
    ]

    const metricKey = (entry: MetricEntry): string => `${entry.isPrimary ? 'primary' : 'secondary'}-${entry.index}`

    const runSingleComparison = useCallback(
        async (entry: MetricEntry): Promise<void> => {
            const key = metricKey(entry)
            setResults((prev) => ({
                ...prev,
                [key]: {
                    direct: { ...EMPTY_PATH_RESULT, loading: true },
                    precomputed: { ...EMPTY_PATH_RESULT, loading: true },
                },
            }))

            const [direct, precomputed] = await Promise.all([
                runPathQuery(entry.metric, experimentId, 'direct', featureFlags),
                runPathQuery(entry.metric, experimentId, 'precomputed', featureFlags),
            ])

            setResults((prev) => ({ ...prev, [key]: { direct, precomputed } }))
        },
        [experimentId, featureFlags]
    )

    const runAll = useCallback(async (): Promise<void> => {
        setRunAllInProgress(true)

        // Mark all as loading
        const loadingState: Record<string, { direct: PathResult; precomputed: PathResult }> = {}
        for (const entry of allMetrics) {
            loadingState[metricKey(entry)] = {
                direct: { ...EMPTY_PATH_RESULT, loading: true },
                precomputed: { ...EMPTY_PATH_RESULT, loading: true },
            }
        }
        setResults(loadingState)

        // Each task runs both paths for one metric
        const tasks = allMetrics.map((entry) => async () => {
            const [direct, precomputed] = await Promise.all([
                runPathQuery(entry.metric, experimentId, 'direct', featureFlags),
                runPathQuery(entry.metric, experimentId, 'precomputed', featureFlags),
            ])
            setResults((prev) => ({ ...prev, [metricKey(entry)]: { direct, precomputed } }))
        })

        await runWithLimit(tasks, COMPARISON_CONCURRENCY_LIMIT)
        setRunAllInProgress(false)
    }, [allMetrics, experimentId, featureFlags])

    if (allMetrics.length === 0) {
        return <div className="text-muted">No metrics configured.</div>
    }

    const anyLoading = runAllInProgress || Object.values(results).some((r) => r.direct.loading || r.precomputed.loading)

    return (
        <div>
            <div className="flex items-center justify-between mb-3">
                <div>
                    <h3 className="font-semibold mb-1">Execution path comparison</h3>
                    <p className="text-muted text-sm">
                        Run each metric through both direct scan and precomputed paths to compare timing and results.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={runAll}
                    disabledReason={anyLoading ? 'Running...' : undefined}
                >
                    {runAllInProgress ? <Spinner className="mr-1" /> : null}
                    Run all
                </LemonButton>
            </div>
            {allMetrics.map((entry) => {
                const key = metricKey(entry)
                const result = results[key]
                const title = entry.metric.name || getDefaultMetricTitle(entry.metric)
                const isLoading = result?.direct.loading || result?.precomputed.loading

                return (
                    <div key={key} className="border rounded p-3 mb-3">
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-semibold">
                                {entry.isPrimary ? 'Primary' : 'Secondary'} #{entry.index + 1}: {title}
                            </span>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => runSingleComparison(entry)}
                                disabledReason={isLoading ? 'Running...' : undefined}
                            >
                                {isLoading ? <Spinner className="mr-1" /> : null}
                                Compare paths
                            </LemonButton>
                        </div>
                        {result && <MetricComparisonResults direct={result.direct} precomputed={result.precomputed} />}
                    </div>
                )
            })}
        </div>
    )
}

export function ExperimentDebugPanel({ experimentId }: { experimentId: number | null }): JSX.Element {
    const [activeTab, setActiveTab] = useState('query-log')

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={setActiveTab}
            tabs={[
                {
                    key: 'query-log',
                    label: 'Query log',
                    content: <DebugCHQueries experimentId={experimentId} />,
                },
                ...(experimentId != null
                    ? [
                          {
                              key: 'path-comparison',
                              label: 'Path comparison',
                              content: <ExperimentExecutionPathComparison experimentId={experimentId} />,
                          },
                      ]
                    : []),
            ]}
        />
    )
}
