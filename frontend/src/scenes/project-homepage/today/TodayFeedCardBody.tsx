import { type ReactNode, Suspense, lazy } from 'react'

import { retryImport } from 'lib/utils/retryImport'

import type { TodayRowTone } from './TodayRow'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export interface TodayFeedCardBodyProps {
    tone: TodayRowTone
    quote?: string | null
    lead?: string | null
    figure?: { value: string; label: string } | null
    series?: number[] | null
    chips?: ReactNode
}

export function TodayFeedCardBody({ tone, quote, lead, figure, series, chips }: TodayFeedCardBodyProps): JSX.Element {
    const trend = series && series.length > 1 ? series : null
    return (
        <div className="TodayFeedCard__body">
            {quote && (
                <p className="TodayFeedCard__quote font-mono" title={quote}>
                    {quote}
                </p>
            )}
            {lead && <p className="TodayFeedCard__lead">{lead}</p>}
            {figure && (
                <p className="TodayFeedCard__figure">
                    <strong translate="no">{figure.value}</strong>
                    <span>{figure.label}</span>
                </p>
            )}
            {trend && (
                <div className="TodayFeedCard__trend" aria-hidden>
                    <Suspense fallback={null}>
                        <TodaySparkline
                            values={trend}
                            labels={trend.map((_, index) => String(index))}
                            tone={tone === 'risk' ? 'risk' : 'neutral'}
                            emphasizeLast={1}
                        />
                    </Suspense>
                </div>
            )}
            {chips && <div className="TodayFeedCard__chips">{chips}</div>}
        </div>
    )
}
