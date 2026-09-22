import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { CAPABILITY_COPY, ReadinessHeader } from './ReadinessHeader'
import { SuggestionRow } from './SuggestionRow'

function EmptyState({ scanned, degraded }: { scanned: boolean; degraded: string[] }): JSX.Element {
    if (!scanned) {
        return (
            <div className="text-center py-8 text-secondary">
                <p>Scan your project to see what's worth fixing.</p>
            </div>
        )
    }
    // A degraded plan is missing whole checks, so "every check passed" is a clean bill
    // of health we can't give.
    if (degraded.length) {
        return (
            <div className="flex items-center justify-center gap-2 py-8 text-secondary">
                <span>Nothing to fix in the checks that ran — {degraded.length} couldn't be completed.</span>
            </div>
        )
    }
    return (
        <div className="flex items-center justify-center gap-2 py-8 text-secondary">
            <IconCheckCircle className="text-success text-xl" />
            <span>Nothing to fix — every check passed.</span>
        </div>
    )
}

export function SuggestedActions(): JSX.Element {
    const {
        visibleSuggestions,
        listedSuggestions,
        focusedCapability,
        safeBatch,
        setupPlan,
        setupPlanLoading,
        applyingIds,
        dismissedSuggestions,
        showDismissed,
        degraded,
    } = useValues(setupPlanLogic)
    const {
        loadSetupPlan,
        reviewSafeBatch,
        reviewSuggestion,
        focusCapability,
        toggleShowDismissed,
        restoreAllDismissed,
    } = useActions(setupPlanLogic)

    const isBatchApplying = safeBatch.some((s) => applyingIds.includes(s.id))

    return (
        <div className="deprecated-space-y-4">
            <div className="flex items-start justify-between gap-4">
                <p className="text-secondary max-w-xl mb-0">
                    What we found in your data, and what to do about it. Every suggestion shows the numbers behind it,
                    so you can check it before applying.
                </p>
                <div className="flex items-center gap-2 shrink-0">
                    {/* Hidden while filtered: the batch is over every safe suggestion,
                        not the handful on screen, and a count that disagrees with the
                        list is how someone applies more than they meant to. */}
                    {safeBatch.length > 0 && !focusedCapability && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={isBatchApplying}
                            onClick={reviewSafeBatch}
                            // "Safe" is about what can go in one batch, not a verdict on
                            // the rest — say so, because the label alone reads as one.
                            tooltip="Reversible changes we're confident enough about to apply together — you still get a preview of exactly what they change. The rest aren't risky, they need a decision only you can make."
                        >
                            Review {safeBatch.length} safe change{safeBatch.length === 1 ? '' : 's'}
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconRefresh />}
                        loading={setupPlanLoading}
                        // A rescan while an apply is in flight lands a plan built before
                        // that change, and the row it fixed comes back.
                        disabledReason={applyingIds.length ? 'Waiting for the current change to finish' : undefined}
                        onClick={() => loadSetupPlan({ refresh: true })}
                    >
                        {setupPlan ? 'Rescan' : 'Scan'}
                    </LemonButton>
                </div>
            </div>

            {setupPlan && <ReadinessHeader />}

            {focusedCapability && (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <span>
                        Showing the {listedSuggestions.length} of {visibleSuggestions.length} suggestions that affect{' '}
                        <strong>{CAPABILITY_COPY[focusedCapability]?.label ?? focusedCapability}</strong>.
                    </span>
                    <LemonButton size="xsmall" type="tertiary" onClick={() => focusCapability(null)}>
                        Show all
                    </LemonButton>
                </div>
            )}

            {setupPlanLoading && !setupPlan ? (
                <div className="deprecated-space-y-2">
                    <LemonSkeleton className="h-16 w-full" />
                    <LemonSkeleton className="h-16 w-full" />
                    <LemonSkeleton className="h-16 w-full" />
                </div>
            ) : listedSuggestions.length ? (
                <div className="border rounded bg-bg-light">
                    {listedSuggestions.map((suggestion) => (
                        <SuggestionRow key={suggestion.id} suggestion={suggestion} onReview={reviewSuggestion} />
                    ))}
                </div>
            ) : focusedCapability ? (
                // Reachable: a capability can be blocked by something we surface no
                // suggestion for.
                <div className="flex items-center justify-center gap-2 py-8 text-secondary">
                    <span>Nothing here changes that metric.</span>
                    <LemonButton size="small" type="secondary" onClick={() => focusCapability(null)}>
                        Show everything
                    </LemonButton>
                </div>
            ) : (
                <EmptyState scanned={!!setupPlan} degraded={degraded} />
            )}

            {/* So dismissing isn't a one-way door — a dismissal that turns out to matter
                costs one click to get back. */}
            {dismissedSuggestions.length > 0 && (
                <div className="deprecated-space-y-2">
                    <div className="flex items-center justify-between gap-4 text-sm text-secondary">
                        <span>
                            {dismissedSuggestions.length} hidden. Dismissing hides a suggestion — it doesn't fix it.
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                            <LemonButton size="small" type="secondary" onClick={toggleShowDismissed}>
                                {showDismissed ? 'Hide' : 'Review hidden'}
                            </LemonButton>
                            <LemonButton size="small" type="tertiary" onClick={restoreAllDismissed}>
                                Restore all
                            </LemonButton>
                        </div>
                    </div>
                    {showDismissed && (
                        <div className="border rounded bg-bg-light opacity-75">
                            {dismissedSuggestions.map((suggestion) => (
                                <SuggestionRow
                                    key={suggestion.id}
                                    suggestion={suggestion}
                                    onReview={reviewSuggestion}
                                    isDismissed
                                />
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
