import { IconClock, IconWarning } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

// Inlined from products/ai_observability/frontend/utils to keep the eagerly-loaded widget catalog
// off the AI observability logic graph (its utils module imports trace/evaluation logics).
const usdFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 })

function formatTraceCost(cost: number): string {
    return usdFormatter.format(cost)
}

function formatTraceLatency(latency: number): string {
    return `${Math.round(latency * 100) / 100} s`
}

export type LlmAnalyticsTracesWidgetTrace = {
    id: string
    traceName?: string | null
    createdAt: string
    totalLatency?: number | null
    totalCost?: number | null
    inputTokens?: number | null
    outputTokens?: number | null
    errorCount?: number | null
    distinctId?: string | null
    person?: { distinct_id?: string; uuid?: string; properties?: Record<string, unknown> } | null
}

export function LlmAnalyticsTracesWidgetRowSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-1 px-3 py-2">
            <div className="flex items-center gap-2">
                <LemonSkeleton className="h-4 flex-1" />
                <div className="flex w-44 shrink-0 items-center gap-2">
                    <LemonSkeleton className="size-5 shrink-0 rounded-full" />
                    <LemonSkeleton className="h-4 flex-1" />
                </div>
                <LemonSkeleton className="h-4 w-28 shrink-0" />
            </div>
            <LemonSkeleton className="h-3 w-56" />
        </div>
    )
}

export function LlmAnalyticsTracesWidgetRow({ trace }: { trace: LlmAnalyticsTracesWidgetTrace }): JSX.Element {
    const hasErrors = (trace.errorCount ?? 0) > 0

    return (
        <Link
            to={urls.aiObservabilityTrace(trace.id)}
            target="_blank"
            subtle
            className="@container flex flex-col gap-0.5 px-3 py-2 hover:bg-surface-secondary focus-visible:outline-offset-[-2px]"
            data-attr="llm-analytics-traces-widget-row"
        >
            <div className="flex items-center gap-2">
                <span className="flex min-w-0 flex-1 items-center gap-1 text-sm font-medium">
                    {hasErrors ? <IconWarning className="shrink-0 text-danger" /> : null}
                    <span className="min-w-0 truncate">{trace.traceName || 'Trace'}</span>
                </span>
                {/* Fixed person + date columns keep the avatar at a constant x and the name truncation
                    consistent across rows regardless of the relative-time length. */}
                <div className="flex w-44 shrink-0 items-center gap-2 text-xs">
                    {trace.person || trace.distinctId ? (
                        <PersonDisplay
                            person={{
                                distinct_id: trace.person?.distinct_id ?? trace.distinctId ?? undefined,
                                properties: trace.person?.properties ?? {},
                            }}
                            className="flex min-w-0 flex-1 [&>span]:min-w-0"
                            withIcon
                            noLink
                            noPopover
                        />
                    ) : null}
                </div>
                <span className="w-28 shrink-0 truncate text-right text-xs text-muted">
                    <TZLabel time={trace.createdAt} />
                </span>
            </div>
            <div className="flex min-h-4 min-w-0 items-center gap-3 text-xs text-muted">
                {typeof trace.totalLatency === 'number' ? (
                    <span className="flex shrink-0 items-center gap-1">
                        <IconClock />
                        {formatTraceLatency(trace.totalLatency)}
                    </span>
                ) : null}
                {typeof trace.totalCost === 'number' ? (
                    <span className="shrink-0">{formatTraceCost(trace.totalCost)}</span>
                ) : null}
                {typeof trace.inputTokens === 'number' || typeof trace.outputTokens === 'number' ? (
                    <span className="shrink-0">
                        {trace.inputTokens ?? 0} → {trace.outputTokens ?? 0} tokens
                    </span>
                ) : null}
            </div>
        </Link>
    )
}
