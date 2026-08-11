import { useActions, useValues } from 'kea'

import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { SuggestionRow } from './SuggestionRow'

/** Which part of Setup owns each kind of suggestion.
 *
 * Lives on the frontend because `SetupSection` is a UI concept — MCP and API
 * consumers get the flat ranked list and have no sections to route into.
 *
 * A kind missing from this map still shows up in "Suggested setup"; it just doesn't
 * appear in a section. That's the safe direction for a kind added backend-first.
 */
export const SECTION_BY_KIND: Record<string, SetupSection> = {
    connect_source: SetupSection.SOURCES,
    reconnect_oauth: SetupSection.SOURCES,
    fix_sync: SetupSection.SOURCES,
    map_schema_columns: SetupSection.SOURCES,

    add_source_mapping: SetupSection.UTM_MAPPING,
    add_campaign_name_mapping: SetupSection.UTM_MAPPING,
    switch_campaign_match_field: SetupSection.UTM_MAPPING,
    remove_mapping: SetupSection.UTM_MAPPING,

    // Untagged ad URLs and orphaned campaigns are what the audit is about.
    fix_platform_urls: SetupSection.INTEGRATION_HEALTH,

    create_conversion_goal: SetupSection.CONVERSION_GOALS,
    fix_conversion_goal: SetupSection.CONVERSION_GOALS,
    mark_goal_as_revenue: SetupSection.CONVERSION_GOALS,
    mark_goal_as_customer: SetupSection.CONVERSION_GOALS,
}

export function suggestionsForSection(suggestions: Suggestion[], section: SetupSection): Suggestion[] {
    return suggestions.filter((suggestion) => SECTION_BY_KIND[suggestion.kind] === section)
}

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
                <SuggestionRow key={suggestion.id} suggestion={suggestion} onReview={reviewSuggestion} />
            ))}
        </div>
    )
}
