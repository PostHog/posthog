import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonBanner, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { OnlinePerformanceRow, autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { EmptyTab } from './EmptyTab'
import { MetricTrendCard } from './MetricTrendCard'

const MODEL_ROLE: Record<string, { type: 'success' | 'default' | 'highlight'; label: string }> = {
    champion: { type: 'success', label: 'Champion' },
    challenger: { type: 'highlight', label: 'Challenger' },
    archived: { type: 'default', label: 'Archived' },
}

function fmt(value: number | null, decimals = 3): string {
    return value != null ? value.toFixed(decimals) : '—'
}

export function OnlinePerformanceTab(): JSX.Element {
    const { onlinePerformanceRows, runsLoading, runsError } = useValues(autoresearchPipelineLogic)
    const { loadRuns } = useActions(autoresearchPipelineLogic)

    if (runsLoading) {
        return <Spinner />
    }

    if (runsError) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Retry', onClick: () => loadRuns(), 'data-attr': 'autoresearch-model-runs-retry' }}
            >
                Couldn't load this model's scoring runs. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (onlinePerformanceRows.length === 0) {
        return (
            <EmptyTab icon={<IconGraph />} title="No realized performance yet">
                Realized metrics appear once prediction horizons elapse. For each prediction date, PostHog joins your{' '}
                <code>autoresearch_prediction</code> events to actual outcomes and computes AUC, Brier score, and lift.
                Trigger evaluation with the <code>autoresearch-validate-online</code> MCP tool or the{' '}
                <code>autoresearch_validate_online</code> management command.
            </EmptyTab>
        )
    }

    // Champion metric trends over time, oldest → newest, for the sparklines.
    const championRows = onlinePerformanceRows
        .filter((r) => r.emitted_role === 'champion')
        .sort((a, b) => a.prediction_date.localeCompare(b.prediction_date))
    const trend = (pick: (r: OnlinePerformanceRow) => number | null): { date: string; value: number }[] =>
        championRows.filter((r) => pick(r) != null).map((r) => ({ date: r.prediction_date, value: pick(r) as number }))
    const aucTrend = trend((r) => r.realized_auc)
    const brierTrend = trend((r) => r.brier_score)
    const eceTrend = trend((r) => r.calibration_error)

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Realized performance measured after each prediction horizon elapses. AUC and lift here reflect actual
                user outcomes rather than holdout estimates.
            </p>
            <div className="flex flex-wrap gap-3">
                <MetricTrendCard
                    title="Champion realized AUC"
                    points={aucTrend}
                    color="var(--success)"
                    floor={0.5}
                    ceil={1}
                />
                <MetricTrendCard title="Champion Brier score" points={brierTrend} color="var(--warning)" floor={0} />
                <MetricTrendCard
                    title="Champion calibration error (ECE)"
                    points={eceTrend}
                    color="var(--warning)"
                    floor={0}
                />
            </div>
            <LemonTable
                dataSource={onlinePerformanceRows}
                rowKey={(row) => `${row.run_id}-${row.model_id}`}
                columns={[
                    {
                        title: 'Prediction date',
                        render: (_, row) => <span className="font-mono">{row.prediction_date}</span>,
                    },
                    {
                        title: 'Model',
                        tooltip: 'The role the model held when it made these predictions.',
                        render: (_, row) => (
                            <LemonTag type={MODEL_ROLE[row.emitted_role]?.type ?? 'default'}>
                                {MODEL_ROLE[row.emitted_role]?.label ?? row.emitted_role}
                            </LemonTag>
                        ),
                    },
                    { title: 'Users scored', render: (_, row) => row.n_scored.toLocaleString() },
                    {
                        title: 'Realized AUC',
                        render: (_, row) => <span className="font-semibold">{fmt(row.realized_auc)}</span>,
                    },
                    { title: 'Brier score', render: (_, row) => fmt(row.brier_score) },
                    { title: 'Calibration error', render: (_, row) => fmt(row.calibration_error) },
                    { title: 'Lift at 10%', render: (_, row) => `${fmt(row.lift_at_10, 2)}×` },
                    { title: 'Lift at 20%', render: (_, row) => `${fmt(row.lift_at_20, 2)}×` },
                ]}
            />
            <p className="text-xs text-muted">
                Realized AUC: higher is better. Brier score and calibration error (ECE): lower is better. ECE measures
                how far predicted probabilities drift from observed rates. Lift at k%: ratio of positives in the top k%
                vs a random sample, so 2× means twice as many conversions as random.
            </p>
        </div>
    )
}
