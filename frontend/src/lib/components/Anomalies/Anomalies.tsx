import { useActions, useValues } from 'kea'

import { IconSparkles, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { anomaliesLogic } from './anomaliesLogic'
import { AnomalyChart } from './AnomalyChart'
import { AnomalyInterval, AnomalyScoreType, AnomalyWindow } from './types'

type Severity = 'critical' | 'high' | 'moderate'

function scoreSeverity(score: number): Severity {
    if (score >= 0.98) {
        return 'critical'
    }
    if (score >= 0.9) {
        return 'high'
    }
    return 'moderate'
}

const severityBadge: Record<Severity, string> = {
    critical: 'bg-danger-highlight text-danger border-danger/30',
    high: 'bg-warning-highlight text-warning border-warning/30',
    moderate: 'bg-surface-secondary text-muted border-border',
}

const severityBar: Record<Severity, string> = {
    critical: 'bg-danger',
    high: 'bg-warning',
    moderate: 'bg-border-bold',
}

function ratePercent(rate: number): string {
    const pct = rate * 100
    // Sub-1% rates would render as "0%" and lose signal; show one decimal so
    // "0.3%" stays distinguishable from "0%".
    if (pct > 0 && pct < 1) {
        return pct.toFixed(1)
    }
    return String(Math.round(pct))
}

function intervalLabel(interval: string): string {
    switch (interval) {
        case 'hour':
            return 'Hourly'
        case 'day':
            return 'Daily'
        case 'week':
            return 'Weekly'
        case 'month':
            return 'Monthly'
        default:
            return interval
    }
}

function AnomalyRow({ anomaly }: { anomaly: AnomalyScoreType }): JSX.Element {
    const { feedbackByAnomaly } = useValues(anomaliesLogic)
    const { setAnomalyFeedback } = useActions(anomaliesLogic)
    const severity = scoreSeverity(anomaly.score)
    const scorePct = Math.round(anomaly.score * 100)
    const hasSeriesLabel = anomaly.series_label && anomaly.series_label !== anomaly.insight_name
    const feedback = feedbackByAnomaly[anomaly.id]

    const onFeedback = (e: React.MouseEvent, value: 'up' | 'down'): void => {
        e.preventDefault()
        e.stopPropagation()
        if (feedback === value) {
            return
        }
        setAnomalyFeedback(anomaly, value)
    }

    return (
        <Link
            to={urls.insightView(anomaly.insight_short_id as InsightShortId)}
            className="group flex h-32 items-stretch gap-3 border-b border-border px-2 py-2 no-underline transition-colors hover:bg-surface-secondary"
            subtle
        >
            {/* Severity left-edge bar — vertical scan cue */}
            <div className={`w-0.5 shrink-0 rounded-full ${severityBar[severity]}`} aria-hidden />

            {/* Metadata column — tight, left-aligned */}
            <div className="flex w-60 shrink-0 flex-col gap-1">
                <div className="flex items-center gap-1.5">
                    <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-xs font-bold tabular-nums ${severityBadge[severity]}`}
                    >
                        {scorePct}%
                    </span>
                    <LemonTag type="muted" size="small">
                        {intervalLabel(anomaly.interval)}
                    </LemonTag>
                    {anomaly.scored_count > 0 && (
                        <LemonTag
                            type="danger"
                            size="small"
                            title={`${anomaly.anomaly_count} of ${anomaly.scored_count} ticks flagged`}
                        >
                            {ratePercent(anomaly.anomaly_rate)}%
                        </LemonTag>
                    )}
                    {anomaly.timestamp && (
                        <span className="ml-auto font-mono text-[10px] font-semibold tabular-nums text-danger">
                            {dayjs(anomaly.timestamp).format('MMM D')}
                        </span>
                    )}
                </div>
                <div className="min-w-0">
                    <div
                        className="line-clamp-1 text-sm font-semibold leading-tight text-default group-hover:text-accent"
                        title={anomaly.insight_name}
                    >
                        {anomaly.insight_name}
                    </div>
                    {hasSeriesLabel && (
                        <div className="line-clamp-1 text-xs text-muted" title={anomaly.series_label}>
                            {anomaly.series_label}
                        </div>
                    )}
                </div>
                <div className="mt-auto flex items-center justify-between gap-1">
                    {anomaly.timestamp && (
                        <div className="text-[11px] text-muted">
                            <TZLabel time={anomaly.timestamp} />
                        </div>
                    )}
                    <div className="flex items-center gap-0.5">
                        <LemonButton
                            size="xsmall"
                            icon={feedback === 'up' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                            tooltip={feedback === 'up' ? 'Marked helpful' : 'Helpful'}
                            active={feedback === 'up'}
                            onClick={(e) => onFeedback(e, 'up')}
                        />
                        <LemonButton
                            size="xsmall"
                            icon={feedback === 'down' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                            tooltip={feedback === 'down' ? 'Marked not helpful' : 'Not helpful'}
                            active={feedback === 'down'}
                            onClick={(e) => onFeedback(e, 'down')}
                        />
                    </div>
                </div>
            </div>

            {/* Chart column — the main focus */}
            <div className="flex min-w-0 flex-1 items-stretch">
                {anomaly.data_snapshot?.data?.length ? (
                    <AnomalyChart anomaly={anomaly} />
                ) : (
                    <div className="flex items-center text-xs italic text-muted">No series data</div>
                )}
            </div>
        </Link>
    )
}

export function Anomalies(): JSX.Element {
    const { filteredAnomalies, anomaliesLoading, window, search, intervalFilter } = useValues(anomaliesLogic)
    const { setWindow, setSearch, setIntervalFilter } = useActions(anomaliesLogic)

    return (
        <div className="space-y-3">
            {/* Sticky filter bar */}
            <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-border bg-primary py-2">
                <LemonSelect
                    size="small"
                    value={window}
                    onChange={(value) => setWindow(value as AnomalyWindow)}
                    options={[
                        { value: '24h', label: 'Last 24 hours' },
                        { value: '7d', label: 'Last 7 days' },
                        { value: '30d', label: 'Last 30 days' },
                    ]}
                />
                <LemonSegmentedButton
                    size="small"
                    value={intervalFilter}
                    onChange={(value) => setIntervalFilter(value as AnomalyInterval)}
                    options={[
                        { value: '', label: 'All' },
                        { value: 'hour', label: 'Hourly' },
                        { value: 'day', label: 'Daily' },
                        { value: 'week', label: 'Weekly' },
                        { value: 'month', label: 'Monthly' },
                    ]}
                />
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search insights..."
                    value={search}
                    onChange={setSearch}
                    className="max-w-60"
                />
                <div className="ml-auto flex items-center gap-1 text-xs text-muted">
                    <IconSparkles className="text-warning" />
                    <span className="font-mono tabular-nums">{filteredAnomalies.length}</span>
                    <span>series</span>
                    <span className="text-border-bold">·</span>
                    <span>sorted by top score</span>
                </div>
            </div>

            {anomaliesLoading && filteredAnomalies.length === 0 ? (
                <div className="py-16 text-center text-sm text-muted">Loading anomalies…</div>
            ) : filteredAnomalies.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-16 text-center">
                    <IconSparkles className="text-2xl text-muted" />
                    <div className="text-sm font-medium text-default">No anomalies in this window</div>
                    <div className="max-w-md text-xs text-muted">
                        Anomaly detection monitors your recently viewed time-series insights. Try widening the window or
                        changing the interval.
                    </div>
                </div>
            ) : (
                <div>
                    {filteredAnomalies.map((a: AnomalyScoreType) => (
                        <AnomalyRow key={a.id} anomaly={a} />
                    ))}
                </div>
            )}
        </div>
    )
}
