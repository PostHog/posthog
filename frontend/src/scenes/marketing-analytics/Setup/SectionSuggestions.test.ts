import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { SECTION_BY_KIND, suggestionsForSection } from './sectionRouting'

const suggestion = (kind: string, id = kind): Suggestion =>
    ({
        id,
        kind,
        source: 'deterministic',
        severity: 'warning',
        confidence: 0.8,
        title: kind,
        evidence: '',
        unlocks: [],
        apply: null,
        also_recommended: [],
        safe_to_batch: false,
        rank_score: 0,
        integration: null,
        deep_link: null,
        docs_url: null,
        spend_at_risk: 0,
        event_volume: 0,
    }) as Suggestion

describe('suggestionsForSection', () => {
    it('routes each kind to the section that owns it', () => {
        const all = [
            suggestion('fix_sync'),
            suggestion('reconnect_oauth'),
            suggestion('add_source_mapping'),
            suggestion('remove_mapping'),
            suggestion('mark_goal_as_revenue'),
            suggestion('fix_platform_urls'),
        ]

        expect(suggestionsForSection(all, SetupSection.SOURCES).map((s) => s.kind)).toEqual([
            'fix_sync',
            'reconnect_oauth',
        ])
        expect(suggestionsForSection(all, SetupSection.UTM_MAPPING).map((s) => s.kind)).toEqual([
            'add_source_mapping',
            'remove_mapping',
        ])
        expect(suggestionsForSection(all, SetupSection.CONVERSION_GOALS).map((s) => s.kind)).toEqual([
            'mark_goal_as_revenue',
        ])
        expect(suggestionsForSection(all, SetupSection.INTEGRATION_HEALTH).map((s) => s.kind)).toEqual([
            'fix_platform_urls',
        ])
    })

    it('leaves an unrouted kind out of every section rather than guessing', () => {
        // A kind added backend-first still shows in "Suggested setup"; it just doesn't
        // claim a section it might not belong to.
        const all = [suggestion('some_future_kind')]

        for (const section of Object.values(SetupSection)) {
            expect(suggestionsForSection(all, section)).toEqual([])
        }
    })

    it('routes every kind the plan can emit', () => {
        // Guards against a new backend kind silently never appearing in a section.
        const emitted = [
            'connect_source',
            'reconnect_oauth',
            'fix_sync',
            'map_schema_columns',
            'add_source_mapping',
            'add_campaign_name_mapping',
            'switch_campaign_match_field',
            'remove_mapping',
            'fix_platform_urls',
            'create_conversion_goal',
            'fix_conversion_goal',
            'mark_goal_as_revenue',
            'mark_goal_as_customer',
        ]

        expect(emitted.filter((kind) => !SECTION_BY_KIND[kind])).toEqual([])
    })
})
