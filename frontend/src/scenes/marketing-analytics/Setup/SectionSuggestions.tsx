import { useActions, useValues } from 'kea'

import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { suggestionsForSection } from './sectionRouting'
import { SuggestionRow } from './SuggestionRow'

/** The suggestions that belong to one section, rendered above its manual controls.
 *
 * Deliberately the same rows as "Suggested setup", not a summary: the ranked list is
 * where you go to ask "what first?", and this is where you land when you're already
 * fixing sources. Same data and the same button — a second, lesser rendering would
 * just be somewhere else to keep in sync.
 *
 * Renders nothing when the section is clean, so a section with no problems doesn't
 * grow an empty "no issues" block above its controls.
 */
export function SectionSuggestions({ section }: { section: SetupSection }): JSX.Element | null {
    const { visibleSuggestions } = useValues(setupPlanLogic)
    const { reviewSuggestion } = useActions(setupPlanLogic)

    const forSection = suggestionsForSection(visibleSuggestions, section)
    if (!forSection.length) {
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
        </div>
    )
}
