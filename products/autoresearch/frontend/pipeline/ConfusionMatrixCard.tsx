import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { ACCURACY_CUTOFFS, confusionDateRange, percent } from '../onlinePerformance'
import { eventName } from '../pipelineQuestion'
import { SectionCard } from './SectionCard'

function Cell({ count, label, tint }: { count: number; label: string; tint: string }): JSX.Element {
    return (
        <div className={`rounded p-3 min-w-0 ${tint}`}>
            <div className="text-xl @xl:text-2xl font-semibold tabular-nums">{count.toLocaleString()}</div>
            <div className="text-xs text-secondary">{label}</div>
        </div>
    )
}

function Rate({
    label,
    value,
    detail,
    tooltip,
}: {
    label: string
    value: number | null
    detail: string
    tooltip: string
}): JSX.Element {
    return (
        <div className="min-w-0 max-w-32 self-center">
            <Tooltip title={tooltip}>
                <div className="text-xs font-semibold text-muted cursor-help">{label}</div>
            </Tooltip>
            <div className="text-lg font-bold tabular-nums">{value != null ? percent(value) : '—'}</div>
            <div className="text-xs text-secondary">{detail}</div>
        </div>
    )
}

/** People the champion flagged at the picked cutoff against what they really did, over the checked dates. */
export function ConfusionMatrixCard(): JSX.Element {
    const { pipeline, accuracyCutoff, championConfusion: confusion } = useValues(autoresearchPipelineLogic)
    const { setAccuracyCutoff } = useActions(autoresearchPipelineLogic)
    const target = pipeline ? eventName(pipeline.target_event) : 'the target event'

    return (
        <SectionCard
            title="Who the model flagged"
            description={
                confusion
                    ? `People scored ${confusion.firstDate === confusion.lastDate ? 'on' : 'from'} ${confusionDateRange(confusion)}`
                    : undefined
            }
            actions={
                <LemonSegmentedButton
                    size="small"
                    value={accuracyCutoff}
                    onChange={(cutoff) => setAccuracyCutoff(cutoff, 'flagged')}
                    options={ACCURACY_CUTOFFS.map(({ key, label }) => ({
                        value: key,
                        label,
                        'data-attr': `autoresearch-model-accuracy-cutoff-${key}`,
                    }))}
                />
            }
        >
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
                        <div className="@container">
                            <div className="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)_auto] gap-2 items-stretch">
                                <div />
                                <div className="text-sm font-semibold">Did it</div>
                                <div className="text-sm font-semibold">Didn't</div>
                                <div />

                                <div className="text-sm font-semibold self-center">Flagged</div>
                                <Cell count={confusion.tp} label="Caught" tint="bg-success-highlight" />
                                <Cell count={confusion.fp} label="False alarm" tint="bg-warning-highlight" />
                                <Rate
                                    label="Hit rate"
                                    value={confusion.precision}
                                    detail={`${confusion.tp.toLocaleString()} of ${confusion.flagged.toLocaleString()} flagged`}
                                    tooltip={`Precision: the share of flagged people who did ${target}.`}
                                />

                                <div className="text-sm font-semibold self-center">Not flagged</div>
                                <Cell count={confusion.fn} label="Missed" tint="bg-danger-highlight" />
                                <Cell count={confusion.tn} label="Correctly ignored" tint="bg-surface-secondary" />
                                <div />

                                <div />
                                <Rate
                                    label="Coverage"
                                    value={confusion.recall}
                                    detail={`${confusion.tp.toLocaleString()} of ${(confusion.tp + confusion.fn).toLocaleString()} who did it`}
                                    tooltip={`Recall: the share of everyone who did ${target} that the model flagged.`}
                                />
                            </div>
                        </div>
                    )}
                </>
            )}
        </SectionCard>
    )
}
