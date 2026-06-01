import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { type WebAnalyticsConversionGoal } from '~/queries/schema/schema-general'

/**
 * Filters handed to the investigate_web_analytics Max tool — mirrors the backend DigestFilterSpec.
 * The tool fetches the data and decomposes the change; Max narrates the investigation.
 */
interface WebAnalyticsInvestigationFilters {
    date_from: string
    date_to: string | null
    compare: boolean
    properties: unknown
    conversion_goal: WebAnalyticsConversionGoal | null
    filter_test_accounts: boolean
    do_path_cleaning: boolean
}

/**
 * Registers the web analytics investigator as a scene-level Max tool (current filters as context, with
 * suggestion chips). Inline per-metric affordances open Max directly with a metric-specific prompt and rely
 * on this registration for the filter context.
 */
export function useInvestigateWebAnalyticsTool(): void {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        dateFilter,
        compareFilter,
        webAnalyticsFilters,
        conversionGoal,
        shouldFilterTestAccounts,
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)

    // useMaxTool keys its registration on JSON.stringify(context), so a fresh object each render is fine.
    const filters: WebAnalyticsInvestigationFilters = {
        date_from: dateFilter.dateFrom ?? '-7d',
        date_to: dateFilter.dateTo ?? null,
        compare: !!compareFilter?.compare,
        properties: webAnalyticsFilters,
        // Already a single-field discriminated object; the backend reads only actionId/customEventName.
        conversion_goal: conversionGoal ?? null,
        filter_test_accounts: shouldFilterTestAccounts,
        do_path_cleaning: isPathCleaningEnabled,
    }

    useMaxTool({
        identifier: 'investigate_web_analytics',
        active: !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_AI_SUMMARY],
        context: { filters },
        contextDescription: {
            text: 'Current web analytics filters',
            icon: iconForType('web_analytics'),
        },
        suggestions: [
            'Why did my traffic change this week?',
            "What's driving my bounce rate?",
            "What's my worst-performing channel?",
        ],
    })
}
