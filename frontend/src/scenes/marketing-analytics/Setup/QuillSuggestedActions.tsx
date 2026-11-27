import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconRefresh } from '@posthog/icons'
import { Button, Empty, EmptyDescription, EmptyHeader, EmptyMedia, ItemGroup, Skeleton, Text } from '@posthog/quill'

import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { CAPABILITY_COPY, ReadinessHeader } from './ReadinessHeader'
import { SuggestionRow } from './SuggestionRow'

export function QuillSuggestedActions({
    editDisabledReason,
    isBatchApplying,
}: {
    editDisabledReason: string | null
    isBatchApplying: boolean
}): JSX.Element {
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

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-xl" />}>
                    What we found in your data, and what to do about it. Every suggestion shows the numbers behind it,
                    so you can check it before applying.
                </Text>
                <div className="flex flex-wrap items-center gap-2">
                    {safeBatch.length > 0 && !focusedCapability && (
                        <Button
                            variant="outline"
                            loading={isBatchApplying}
                            disabledReason={editDisabledReason}
                            onClick={reviewSafeBatch}
                            tooltip="Reversible changes we're confident enough about to apply together — you still get a preview of exactly what they change. The rest aren't risky, they need a decision only you can make."
                        >
                            Review {safeBatch.length} safe change{safeBatch.length === 1 ? '' : 's'}
                        </Button>
                    )}
                    <Button
                        variant="primary"
                        loading={setupPlanLoading}
                        disabledReason={applyingIds.length ? 'Waiting for the current change to finish' : undefined}
                        onClick={() => loadSetupPlan({ refresh: true })}
                    >
                        <IconRefresh />
                        <span>{setupPlan ? 'Rescan' : 'Scan'}</span>
                    </Button>
                </div>
            </div>

            {setupPlan && <ReadinessHeader />}

            {focusedCapability && (
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        Showing the {listedSuggestions.length} of {visibleSuggestions.length} suggestions that affect{' '}
                        <strong>{CAPABILITY_COPY[focusedCapability]?.label ?? focusedCapability}</strong>.
                    </Text>
                    <Button size="xs" onClick={() => focusCapability(null)}>
                        Show all
                    </Button>
                </div>
            )}

            {setupPlanLoading && !setupPlan ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                </div>
            ) : listedSuggestions.length ? (
                <ItemGroup combined>
                    {listedSuggestions.map((suggestion) => (
                        <SuggestionRow key={suggestion.id} suggestion={suggestion} onReview={reviewSuggestion} />
                    ))}
                </ItemGroup>
            ) : focusedCapability ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>Nothing here changes that metric.</EmptyDescription>
                    </EmptyHeader>
                    <Button variant="outline" onClick={() => focusCapability(null)}>
                        Show everything
                    </Button>
                </Empty>
            ) : !setupPlan ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>Scan your project to see what's worth fixing.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : degraded.length ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>
                            Nothing to fix in the checks that ran — {degraded.length} couldn't be completed.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconCheckCircle className="text-success-foreground" />
                        </EmptyMedia>
                        <EmptyDescription>Nothing to fix — every check passed.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )}

            {dismissedSuggestions.length > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {dismissedSuggestions.length} hidden. Dismissing hides a suggestion — it doesn't fix it.
                        </Text>
                        <div className="flex flex-wrap items-center gap-1">
                            <Button variant="outline" onClick={toggleShowDismissed}>
                                {showDismissed ? 'Hide' : 'Review hidden'}
                            </Button>
                            <Button variant="outline" onClick={restoreAllDismissed}>
                                Restore all
                            </Button>
                        </div>
                    </div>
                    {showDismissed && (
                        <ItemGroup combined className="opacity-75">
                            {dismissedSuggestions.map((suggestion) => (
                                <SuggestionRow
                                    key={suggestion.id}
                                    suggestion={suggestion}
                                    onReview={reviewSuggestion}
                                    isDismissed
                                />
                            ))}
                        </ItemGroup>
                    )}
                </div>
            )}
        </div>
    )
}
