import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import type {
    Capability,
    CapabilityReadiness,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

/** Each capability is a column or chart in Marketing analytics, so the chip has to
 * name the thing the user will actually see — an acronym on its own is a riddle. */
export const CAPABILITY_COPY: Record<Capability, { label: string; what: string }> = {
    cost: { label: 'Cost', what: 'What you spent, per platform and campaign.' },
    attribution: { label: 'Attribution', what: 'Which channel a visit or conversion came from.' },
    roas: { label: 'ROAS', what: 'Return on ad spend — revenue divided by cost.' },
    cac: { label: 'Cost per customer', what: 'Ad spend divided by new customers acquired.' },
}

const STATUS_COPY: Record<CapabilityReadiness['status'], string> = {
    unlocked: 'Ready to use',
    partial: 'Partly available',
    blocked: 'Not available yet',
}

function CapabilityChip({
    readiness,
    blockerCount,
    focused,
    onFocus,
}: {
    readiness: CapabilityReadiness
    blockerCount: number
    focused: boolean
    onFocus: () => void
}): JSX.Element {
    const copy = CAPABILITY_COPY[readiness.capability]
    const label = copy?.label ?? readiness.capability
    const clickable = blockerCount > 0

    const tooltip = (
        <div className="deprecated-space-y-1 max-w-xs">
            <div className="font-semibold">
                {label} · {STATUS_COPY[readiness.status]}
            </div>
            {copy && <div>{copy.what}</div>}
            <div className="text-secondary">{readiness.explanation}</div>
            {clickable && (
                <div className="text-secondary">
                    Click to show the {blockerCount} suggestion{blockerCount === 1 ? '' : 's'} that would change this.
                </div>
            )}
        </div>
    )

    // Only `unlocked` counts towards "N of M ready" above, so only `unlocked` gets
    // full-strength text. Grouping `partial` with ready would contradict that count
    // on the very same line.
    //
    // No status icon, and no per-status colour. A yellow warning glyph plus bright
    // text made the one `partial` chip the loudest thing in the row, which reads as
    // "this one is selected" — and the status is already in the tooltip, the count and
    // the progress bar. Background is now reserved for exactly one meaning: focused.
    const ready = readiness.status === 'unlocked'

    return (
        <Tooltip title={tooltip}>
            <button
                type="button"
                disabled={!clickable}
                onClick={onFocus}
                aria-pressed={focused}
                className={`flex items-center gap-1.5 rounded border px-2 py-1 text-sm ${
                    focused ? 'border-accent bg-accent-highlight-secondary' : 'bg-bg-light'
                } ${clickable ? 'cursor-pointer' : 'cursor-default'}`}
            >
                <span className={ready || focused ? undefined : 'text-muted'}>{label}</span>
                {clickable && (
                    <span className="text-xs text-secondary tabular-nums" aria-label={`${blockerCount} suggestions`}>
                        {blockerCount}
                    </span>
                )}
            </button>
        </Tooltip>
    )
}

export function ReadinessHeader(): JSX.Element {
    const { readiness, degraded, truncated, setupPlanLoading, visibleSuggestions, focusedCapability } =
        useValues(setupPlanLogic)
    const { focusCapability } = useActions(setupPlanLogic)

    if (setupPlanLoading && !readiness.length) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-4 w-64" />
                <LemonSkeleton className="h-8 w-full" />
            </div>
        )
    }

    const unlocked = readiness.filter((entry) => entry.status === 'unlocked').length
    const total = readiness.length

    return (
        <div className="deprecated-space-y-3">
            {total > 0 && (
                <div className="deprecated-space-y-2">
                    {/* Without this line the chips read as a list of failures. They are a
                        list of metrics, and most of a new project's are legitimately not
                        available yet — which is the point of the tab, not a fault. */}
                    <div className="flex items-baseline gap-2 text-xs text-secondary">
                        <span className="font-semibold uppercase tracking-wide">What you can measure right now</span>
                        <span>
                            {unlocked} of {total} ready
                        </span>
                    </div>
                    <div className="flex items-center flex-wrap gap-2">
                        {readiness.map((entry) => (
                            <CapabilityChip
                                key={entry.capability}
                                readiness={entry}
                                blockerCount={
                                    visibleSuggestions.filter((suggestion) =>
                                        suggestion.unlocks.includes(entry.capability)
                                    ).length
                                }
                                focused={focusedCapability === entry.capability}
                                onFocus={() => focusCapability(entry.capability)}
                            />
                        ))}
                    </div>
                    <LemonProgress percent={(unlocked / total) * 100} />
                </div>
            )}

            {/* Both of these say "don't read the numbers above as the whole truth" —
                the plan is assembled from independently failing services over capped
                queries, and hiding that would make a partial answer look authoritative. */}
            {degraded.length > 0 && (
                <LemonBanner type="warning">
                    Some checks could not run ({degraded.join(', ')}), so this list is incomplete. Reload to try again.
                </LemonBanner>
            )}
            {truncated && (
                <LemonBanner type="info">
                    You have more campaigns or UTM values than we analyse in one pass, so the figures below are
                    approximate — they cover your highest-spend campaigns and highest-volume UTM values.
                </LemonBanner>
            )}
        </div>
    )
}
