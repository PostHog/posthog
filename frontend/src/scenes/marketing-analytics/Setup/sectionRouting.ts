import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

/** Section names, kept here rather than in `SETUP_SECTIONS` so a suggestion row can
 * name where it's sending you without importing every settings component. */
export const SECTION_LABEL: Record<SetupSection, string> = {
    [SetupSection.SUGGESTIONS]: 'Suggested setup',
    [SetupSection.SOURCES]: 'Ad platforms & sources',
    [SetupSection.CONVERSION_GOALS]: 'Conversion goals',
    [SetupSection.UTM_MAPPING]: 'UTM & campaign mapping',
    [SetupSection.INTEGRATION_HEALTH]: 'Integration health',
    [SetupSection.ATTRIBUTION]: 'Attribution',
    [SetupSection.GENERAL]: 'General',
}

/** Which part of Setup owns each kind of suggestion. A missing kind still shows up in
 * "Suggested setup", just not in a section — the safe direction for one added
 * backend-first. */
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
