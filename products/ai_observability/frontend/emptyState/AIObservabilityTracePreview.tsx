import { sparkPaths } from 'lib/components/ProductEmptyState/previewSparkline'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'

import slackLogo from 'public/services/slack.png'

interface PreviewSession {
    user: string
    title: string
    generations: string
    duration: string
    negative?: boolean
}

// Example sessions - hand-authored, not real data. Shaped like the sessions tab:
// the person, what they were doing, and how the session went.
const SESSIONS: PreviewSession[] = [
    { user: 'sofia', title: 'Draft onboarding email', generations: '14 gens', duration: '6m' },
    { user: 'liam', title: 'Debug a failing SQL query', generations: '9 gens', duration: '3m' },
    { user: 'ava', title: 'Cancel subscription flow', generations: '21 gens', duration: '11m', negative: true },
    { user: 'noah', title: 'Summarize meeting notes', generations: '5 gens', duration: '2m' },
    { user: 'mia', title: 'Translate product docs', generations: '7 gens', duration: '4m' },
]

// A hand-authored series for the sparkline - flat baseline with a spike at the end,
// matching the "negative sentiment spiked" alert below it.
const SPARK = [3, 4, 3, 3, 4, 3, 4, 3, 4, 6, 10, 15]
const { line, area } = sparkPaths(SPARK)

/**
 * Example-data preview for the AI observability empty state: a sessions list plus
 * a negative-sentiment tile with its Slack alert - static rows, no timers, per the
 * preview rules in the `building-product-empty-states` skill.
 */
export function AIObservabilityTracePreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="rounded-md border border-primary bg-surface-primary p-3">
                <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-semibold">Sessions</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                {mode === 'waiting-for-data' ? (
                    <div className="mb-1 flex items-center gap-2 rounded border border-dashed border-primary px-2 py-1.5 text-xs text-secondary">
                        <Spinner className="text-sm" />
                        Listening for your first generation…
                    </div>
                ) : null}

                <div className="flex flex-col">
                    {SESSIONS.map((session, i) => (
                        <div
                            key={i}
                            className="flex items-center gap-2 border-b border-primary px-1 py-1.5 text-xs last:border-b-0"
                        >
                            <span className="w-9 shrink-0 text-secondary">{session.user}</span>
                            <span className="min-w-0 truncate font-medium">{session.title}</span>
                            {session.negative ? (
                                <LemonTag size="small" type="danger">
                                    negative
                                </LemonTag>
                            ) : null}
                            <span className="ml-auto shrink-0 text-secondary">{session.generations}</span>
                            <span className="w-7 shrink-0 text-right text-secondary tabular-nums">
                                {session.duration}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="rounded-md border border-primary bg-surface-primary p-3">
                <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-semibold">Negative sentiment · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="mb-2 text-2xl font-bold tabular-nums">
                    4.6%
                    <span className="ml-2 align-middle text-xs font-semibold text-danger">▲ spiking</span>
                </div>

                <div className="text-danger">
                    <svg className="h-10 w-full" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
                        <path d={area} fill="currentColor" opacity={0.12} />
                        <path
                            d={line}
                            fill="none"
                            stroke="currentColor"
                            strokeWidth={1.5}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                </div>

                <div className="mt-2 flex items-center gap-2 rounded border border-primary px-2 py-1.5 text-xs text-secondary">
                    <img src={slackLogo} alt="" className="size-4 shrink-0" />
                    <span className="min-w-0 truncate">
                        Alert sent to <span className="font-semibold text-primary">#ai-quality</span>: negative
                        sentiment spiked
                    </span>
                </div>
            </div>
        </div>
    )
}
