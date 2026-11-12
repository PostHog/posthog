import { useValues } from 'kea'

import { LemonCollapse, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { OnlinePerformanceRowApi } from '../generated/api.schemas'
import { isLiftAtCeiling, liftCeilingNote } from '../modelQuality'
import { percent } from '../onlinePerformance'
import { eventName } from '../pipelineQuestion'

const MODEL_ROLE: Record<string, { type: 'success' | 'default' | 'highlight'; label: string }> = {
    champion: { type: 'success', label: 'Champion' },
    challenger: { type: 'highlight', label: 'Challenger' },
    archived: { type: 'default', label: 'Archived' },
}

function fmt(value: number | null, decimals = 3): string {
    return value != null ? value.toFixed(decimals) : '—'
}

function LiftCell({ lift, share, baseRate }: { lift: number | null; share: number; baseRate: number }): JSX.Element {
    if (lift == null || !isLiftAtCeiling(lift, share, baseRate)) {
        return <>{`${fmt(lift, 2)}×`}</>
    }
    return (
        <Tooltip title={liftCeilingNote(share, baseRate)}>
            <span className="whitespace-nowrap">{`${fmt(lift, 2)}× (near max)`}</span>
        </Tooltip>
    )
}

function fmtPercent(value: number | null | undefined): string {
    return value != null ? percent(value) : '—'
}

function DatesTable({ rows, target }: { rows: OnlinePerformanceRowApi[]; target: string }): JSX.Element {
    return (
        <div className="space-y-2">
            <LemonTable
                dataSource={rows}
                rowKey={(row) => `${row.validation_run_id}-${row.model_id}`}
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
                    {
                        title: 'Lift at 10%',
                        render: (_, row) => <LiftCell lift={row.lift_at_10} share={0.1} baseRate={row.base_rate} />,
                    },
                    {
                        title: 'Lift at 20%',
                        render: (_, row) => <LiftCell lift={row.lift_at_20} share={0.2} baseRate={row.base_rate} />,
                    },
                    {
                        title: 'Precision at 10%',
                        render: (_, row) => fmtPercent(row.confusion?.top_10.precision),
                    },
                    {
                        title: 'Recall at 10%',
                        render: (_, row) => fmtPercent(row.confusion?.top_10.recall),
                    },
                    { title: 'Average precision', render: (_, row) => fmt(row.average_precision) },
                ]}
            />
            <p className="text-xs text-muted mb-0">
                Realized AUC: higher is better. Brier score and calibration error (ECE): lower is better. ECE measures
                how far predicted probabilities drift from observed rates. Lift at k%: ratio of positives in the top k%
                vs a random sample, so 2× means twice as many conversions as random. Precision at 10%: share of the top
                10% who did {target}. Recall at 10%: share of everyone who did it that the top 10% includes. Average
                precision: precision averaged over every cutoff, higher is better.
            </p>
        </div>
    )
}

/** Every checked date, with the live model's dates apart from the dates of earlier models and challengers. */
export function CheckedDatesHistory(): JSX.Element | null {
    const { pipeline, onlinePerformance, liveModelPerformance } = useValues(autoresearchPipelineLogic)
    if (onlinePerformance.length === 0) {
        return null
    }
    const target = pipeline ? eventName(pipeline.target_event) : 'the target event'
    const live = new Set(liveModelPerformance)
    const otherRows = onlinePerformance.filter((row) => !live.has(row))

    return (
        <LemonCollapse
            multiple
            className="bg-surface-primary"
            panels={[
                ...(liveModelPerformance.length > 0
                    ? [
                          {
                              key: 'live',
                              header:
                                  liveModelPerformance.length === 1
                                      ? '1 date for the live model'
                                      : `All ${liveModelPerformance.length} dates for the live model`,
                              content: <DatesTable rows={liveModelPerformance} target={target} />,
                          },
                      ]
                    : []),
                ...(otherRows.length > 0
                    ? [
                          {
                              key: 'other',
                              header: `Other models (${otherRows.length})`,
                              content: <DatesTable rows={otherRows} target={target} />,
                          },
                      ]
                    : []),
            ]}
        />
    )
}
