import type { MarketingAnalyticsConfig } from '~/queries/schema/schema-general'

import { buildApplyDiff } from './applyDiff'

const config = (overrides: Partial<MarketingAnalyticsConfig> = {}): MarketingAnalyticsConfig =>
    ({
        custom_source_mappings: {},
        campaign_name_mappings: {},
        campaign_field_preferences: {},
        conversion_goals: [],
        ...overrides,
    }) as MarketingAnalyticsConfig

describe('buildApplyDiff', () => {
    it('describes adding a source mapping', () => {
        const diff = buildApplyDiff(
            { op: 'add_custom_source_mapping', integration: 'MetaAds', raw_utm_source: 'fb-ads' },
            config()
        )

        expect(diff.isNoop).toBe(false)
        expect(diff.lines).toEqual([
            { setting: 'Custom source mappings', subject: 'Meta Ads', change: 'add', after: 'fb-ads' },
        ])
    })

    it('reports a no-op when the mapping already exists', () => {
        // The apply endpoint treats this as an idempotent success, so the modal has to
        // say "nothing would change" rather than render an empty diff that reads as a bug.
        const diff = buildApplyDiff(
            { op: 'add_custom_source_mapping', integration: 'MetaAds', raw_utm_source: 'fb-ads' },
            config({ custom_source_mappings: { MetaAds: ['fb-ads'] } })
        )

        expect(diff.isNoop).toBe(true)
        expect(diff.lines).toEqual([])
    })

    it('shows the default as the before value for match field', () => {
        // An absent preference means campaign_name. Showing "not set" would suggest
        // matching wasn't happening at all, which isn't true.
        const diff = buildApplyDiff(
            { op: 'set_campaign_field_preference', integration: 'GoogleAds', match_field: 'campaign_id' },
            config()
        )

        expect(diff.lines[0]).toMatchObject({ change: 'update', before: 'campaign name', after: 'campaign id' })
    })

    it('only lists the raw values a campaign mapping actually adds', () => {
        const diff = buildApplyDiff(
            {
                op: 'add_campaign_name_mapping',
                integration: 'GoogleAds',
                clean_name: 'spring_sale',
                raw_values: ['sprng_sale', 'spring_sle'],
            },
            config({ campaign_name_mappings: { GoogleAds: { spring_sale: ['sprng_sale'] } } })
        )

        expect(diff.lines.map((line) => line.after)).toEqual(['spring_sle'])
    })

    it('names the goal being removed rather than its id', () => {
        const diff = buildApplyDiff(
            { op: 'delete_conversion_goal', conversion_goal_id: 'cg_demos' },
            config({ conversion_goals: [{ conversion_goal_id: 'cg_demos', conversion_goal_name: 'Demos' }] as any })
        )

        expect(diff.lines[0]).toMatchObject({ change: 'remove', after: 'Demos' })
    })

    it('renders a goal flag update as a readable before and after', () => {
        const diff = buildApplyDiff(
            { op: 'update_conversion_goal', conversion_goal_id: 'cg_1', patch: { counts_as_revenue: true } },
            config({ conversion_goals: [{ conversion_goal_id: 'cg_1', conversion_goal_name: 'Purchase' }] as any })
        )

        expect(diff.lines[0]).toMatchObject({ change: 'update', before: 'not set', after: 'yes' })
    })

    it('names goal fields the way the goal editor names them', () => {
        // A preview reading `counts_as_revenue` asks the user to know the schema in
        // order to approve a change to it.
        const diff = buildApplyDiff(
            { op: 'update_conversion_goal', conversion_goal_id: 'cg_1', patch: { counts_as_revenue: true } },
            config({ conversion_goals: [{ conversion_goal_id: 'cg_1', conversion_goal_name: 'Purchase' }] as any })
        )

        expect(diff.lines[0].subject).toBe('Purchase › Each conversion is worth money')
    })

    it('passes an unmapped goal field through readably', () => {
        // A field added backend-first should look unpolished, not invisible.
        const diff = buildApplyDiff(
            { op: 'update_conversion_goal', conversion_goal_id: 'cg_1', patch: { some_new_flag: true } },
            config({ conversion_goals: [{ conversion_goal_id: 'cg_1', conversion_goal_name: 'Purchase' }] as any })
        )

        expect(diff.lines[0].subject).toBe('Purchase › some new flag')
    })

    it('produces nothing for an op it cannot describe', () => {
        // Navigate ops have no config change; the modal explains them in words instead.
        expect(buildApplyDiff({ op: 'open_oauth', kind: 'google-ads' }, config()).lines).toEqual([])
    })
})
