import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { ACCURACY_CUTOFFS, PooledConfusion, percent } from '../onlinePerformance'
import { MetricCard } from './MetricCard'

function dateRange({ firstDate, lastDate }: PooledConfusion): string {
    const last = dayjs(lastDate).format('MMM D, YYYY')
    return firstDate === lastDate ? last : `${dayjs(firstDate).format('MMM D')} to ${last}`
}

function Cell({ count, label }: { count: number; label: string }): JSX.Element {
    return (
        <td className="border p-2 text-right">
            <div className="text-base font-semibold tabular-nums">{count.toLocaleString()}</div>
            <div className="text-xs text-muted">{label}</div>
        </td>
    )
}

/** People the champion flagged at the picked cutoff against what they really did, over the checked dates. */
export function ConfusionMatrixCard(): JSX.Element {
    const { pipeline, accuracyCutoff, championConfusion: confusion } = useValues(autoresearchPipelineLogic)
    const { setAccuracyCutoff } = useActions(autoresearchPipelineLogic)
    const target = pipeline?.target_event ?? 'the target event'

    return (
        <section className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold mb-0">
                    Who the model flagged{confusion ? `, ${dateRange(confusion)}` : ''}
                </h3>
                <LemonSegmentedButton
                    size="small"
                    value={accuracyCutoff}
                    onChange={setAccuracyCutoff}
                    options={ACCURACY_CUTOFFS.map(({ key, label }) => ({ value: key, label }))}
                    data-attr="autoresearch-model-accuracy-cutoff"
                />
            </div>
            {!confusion ? (
                <p className="text-sm text-muted mb-0">
                    Precision and recall start from the next checked date. Dates checked before that have no counts.
                </p>
            ) : (
                <>
                    {confusion.datesWithoutCounts > 0 && (
                        <p className="text-xs text-muted mb-0">
                            Precision and recall start from {dayjs(confusion.firstDate).format('MMM D, YYYY')}. Older
                            checked dates have no counts.
                        </p>
                    )}
                    {confusion.flagged === 0 ? (
                        <LemonBanner type="info">
                            No one scored as likely in this period. Pick Top 10% to see how the people with the highest
                            scores did.
                        </LemonBanner>
                    ) : (
                        <div className="flex flex-wrap items-start gap-4">
                            <table className="text-sm border-collapse">
                                <thead>
                                    <tr>
                                        <th />
                                        <th className="p-2 text-right font-semibold">Did {target}</th>
                                        <th className="p-2 text-right font-semibold">Didn't</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <th className="p-2 text-left font-semibold">Flagged</th>
                                        <Cell count={confusion.tp} label="Correct" />
                                        <Cell count={confusion.fp} label="False alarm" />
                                    </tr>
                                    <tr>
                                        <th className="p-2 text-left font-semibold">Not flagged</th>
                                        <Cell count={confusion.fn} label="Missed" />
                                        <Cell count={confusion.tn} label="Correct" />
                                    </tr>
                                </tbody>
                            </table>
                            <div className="grid grid-cols-2 gap-2 min-w-60">
                                <MetricCard
                                    label="Hit rate"
                                    value={confusion.precision != null ? percent(confusion.precision) : '—'}
                                    tooltip={`Precision: the share of flagged people who did ${target}.`}
                                />
                                <MetricCard
                                    label="Coverage"
                                    value={confusion.recall != null ? percent(confusion.recall) : '—'}
                                    tooltip={`Recall: the share of everyone who did ${target} that the model flagged.`}
                                />
                            </div>
                        </div>
                    )}
                </>
            )}
        </section>
    )
}
