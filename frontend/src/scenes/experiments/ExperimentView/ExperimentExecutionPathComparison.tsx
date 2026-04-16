import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { DebugCHQueries } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'

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
import { getDefaultMetricTitle } from '../MetricsView/shared/utils'

interface PathResult {
    response: ExperimentQueryResponse | null
    durationMs: number | null
    error: string | null
    loading: boolean
}

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

function MetricComparison({
    metric,
    metricIndex,
    experimentId,
    isPrimary,
}: {
    metric: ExperimentMetric
    metricIndex: number
    experimentId: number
    isPrimary: boolean
}): JSX.Element {
    const [direct, setDirect] = useState<PathResult>({ response: null, durationMs: null, error: null, loading: false })
    const [precomputed, setPrecomputed] = useState<PathResult>({
        response: null,
        durationMs: null,
        error: null,
        loading: false,
    })

    const runComparison = async (): Promise<void> => {
        setDirect({ response: null, durationMs: null, error: null, loading: true })
        setPrecomputed({ response: null, durationMs: null, error: null, loading: true })

        const runPath = async (mode: 'direct' | 'precomputed', setter: (r: PathResult) => void): Promise<void> => {
            const query = {
                kind: NodeKind.ExperimentQuery as const,
                metric,
                experiment_id: experimentId,
                precomputation_mode: mode,
            }
            const startTime = performance.now()
            try {
                const response = await performQuery(setLatestVersionsOnQuery(query), undefined, 'force_async')
                setter({
                    response: response as ExperimentQueryResponse,
                    durationMs: Math.round(performance.now() - startTime),
                    error: null,
                    loading: false,
                })
            } catch (e: any) {
                setter({
                    response: null,
                    durationMs: Math.round(performance.now() - startTime),
                    error: e?.message || 'Unknown error',
                    loading: false,
                })
            }
        }

        await Promise.all([runPath('direct', setDirect), runPath('precomputed', setPrecomputed)])
    }

    const title = metric.name || getDefaultMetricTitle(metric)
    const hasResults = direct.response && precomputed.response
    const isLoading = direct.loading || precomputed.loading

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
        <div className="border rounded p-3 mb-3">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">
                        {isPrimary ? 'Primary' : 'Secondary'} #{metricIndex + 1}: {title}
                    </span>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={runComparison}
                    disabledReason={isLoading ? 'Running...' : undefined}
                >
                    {isLoading ? <Spinner className="mr-1" /> : null}
                    Compare paths
                </LemonButton>
            </div>

            {(direct.loading || direct.response || direct.error) && (
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
                                    {directSig.chanceToWin != null
                                        ? ` (${(directSig.chanceToWin * 100).toFixed(1)}%)`
                                        : ''}
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

                    {comparisonRows.length > 0 && (
                        <LemonTable dataSource={comparisonRows} columns={columns} size="small" />
                    )}
                </div>
            )}
        </div>
    )
}

function ExperimentExecutionPathComparison({ experimentId }: { experimentId: number }): JSX.Element {
    const { experiment } = useValues(experimentLogic)

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

    if (primaryMetrics.length === 0 && secondaryMetrics.length === 0) {
        return <div className="text-muted">No metrics configured.</div>
    }

    return (
        <div>
            <h3 className="font-semibold mb-2">Execution path comparison</h3>
            <p className="text-muted text-sm mb-3">
                Run each metric through both direct scan and precomputed paths to compare timing and results.
            </p>
            {primaryMetrics.map((metric, i) => (
                <MetricComparison
                    key={`primary-${i}`}
                    metric={metric}
                    metricIndex={i}
                    experimentId={experimentId}
                    isPrimary={true}
                />
            ))}
            {secondaryMetrics.map((metric, i) => (
                <MetricComparison
                    key={`secondary-${i}`}
                    metric={metric}
                    metricIndex={i}
                    experimentId={experimentId}
                    isPrimary={false}
                />
            ))}
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
