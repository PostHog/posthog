import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { suggestionsForSection } from './sectionRouting'
import { SuggestionRow } from './SuggestionRow'

/** One section's suggestions, above its manual controls. The same rows as "Suggested
 * setup" rather than a summary, so there's no second rendering to keep in sync. */
export function SectionSuggestions({ section }: { section: SetupSection }): JSX.Element | null {
    const { visibleSuggestions, dismissedSuggestions, showDismissed } = useValues(setupPlanLogic)
    const { reviewSuggestion, toggleShowDismissed } = useActions(setupPlanLogic)

    const forSection = suggestionsForSection(visibleSuggestions, section)
    const dismissedForSection = suggestionsForSection(dismissedSuggestions, section)
    if (!forSection.length && !dismissedForSection.length) {
        return null
    }

    return (
        <div className="border rounded bg-bg-light mb-4">
            {forSection.map((suggestion) => (
                <SuggestionRow
                    key={suggestion.id}
                    suggestion={suggestion}
                    onReview={reviewSuggestion}
                    currentSection={section}
                />
            ))}
            {dismissedForSection.length > 0 && (
                <>
                    <LemonButton size="small" onClick={toggleShowDismissed} className="m-2">
                        {showDismissed ? 'Hide dismissed' : 'Show dismissed'} ({dismissedForSection.length})
                    </LemonButton>
                    {showDismissed &&
                        dismissedForSection.map((suggestion) => (
                            <SuggestionRow
                                key={suggestion.id}
                                suggestion={suggestion}
                                onReview={reviewSuggestion}
                                currentSection={section}
                                isDismissed
                            />
                        ))}
                </>
            )}
        </div>
    )
}
