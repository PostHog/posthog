import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { Button, ItemGroup } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { suggestionsForSection } from './sectionRouting'
import { SuggestionRow } from './SuggestionRow'

/** One section's suggestions, above its manual controls. The same rows as "Suggested
 * setup" rather than a summary, so there's no second rendering to keep in sync. */
export function SectionSuggestions({ section }: { section: SetupSection }): JSX.Element | null {
    const { visibleSuggestions, dismissedSuggestions } = useValues(setupPlanLogic)
    const { reviewSuggestion } = useActions(setupPlanLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const [dismissedSection, setDismissedSection] = useState<SetupSection | null>(null)
    const showDismissed = dismissedSection === section
    const forSection = suggestionsForSection(visibleSuggestions, section)
    const dismissedForSection = suggestionsForSection(dismissedSuggestions, section)
    if (!forSection.length && !dismissedForSection.length) {
        return null
    }

    const toggleDismissed = (): void => setDismissedSection(showDismissed ? null : section)
    const rows = forSection.map((suggestion) => (
        <SuggestionRow
            key={suggestion.id}
            suggestion={suggestion}
            onReview={reviewSuggestion}
            currentSection={section}
        />
    ))
    const dismissedRows = dismissedForSection.map((suggestion) => (
        <SuggestionRow
            key={suggestion.id}
            suggestion={suggestion}
            onReview={reviewSuggestion}
            currentSection={section}
            isDismissed
        />
    ))

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                {forSection.length > 0 && <ItemGroup combined>{rows}</ItemGroup>}
                {dismissedForSection.length > 0 && (
                    <>
                        <div>
                            <Button onClick={toggleDismissed}>
                                {showDismissed ? 'Hide dismissed' : 'Show dismissed'} ({dismissedForSection.length})
                            </Button>
                        </div>
                        {showDismissed && <ItemGroup combined>{dismissedRows}</ItemGroup>}
                    </>
                )}
            </div>
        )
    }

    return (
        <div className="border rounded bg-bg-light mb-4">
            {rows}
            {dismissedForSection.length > 0 && (
                <>
                    <LemonButton size="small" onClick={toggleDismissed} className="m-2">
                        {showDismissed ? 'Hide dismissed' : 'Show dismissed'} ({dismissedForSection.length})
                    </LemonButton>
                    {showDismissed && dismissedRows}
                </>
            )}
        </div>
    )
}
