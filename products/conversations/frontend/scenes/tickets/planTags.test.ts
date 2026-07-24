import { PLAN_GROUPS, planLabel, planRank } from './planTags'

describe('PLAN_GROUPS', () => {
    it('lists the groups in triage-first priority order', () => {
        expect(PLAN_GROUPS.map((g) => g.label)).toEqual([
            'Triage',
            'Churn risk',
            'Top 20',
            'Enterprise',
            'Onboarding',
            'Scale & Teams & YC',
            'Boost & Startup & Pay-as-you-go paying',
            'Pay-as-you-go free',
            'Free plan',
            'Community',
        ])
    })

    it('never routes one tag to two groups', () => {
        const all = PLAN_GROUPS.flatMap((g) => g.tags)
        expect(new Set(all).size).toBe(all.length)
    })
})

describe('planLabel', () => {
    it.each([
        // Live SLA-workflow and handbook vocabulary
        ['support_needs_triage', 'Triage'],
        ['churn_risk', 'Churn risk'],
        ['top_20', 'Top 20'],
        ['plan_enterprise', 'Enterprise'],
        ['goodwill_enterprise', 'Enterprise'],
        ['unknown_slack_default_enterprise', 'Enterprise'],
        ['unknown_msteams_default_enterprise', 'Enterprise'],
        ['new_customer_onboarding', 'Onboarding'],
        ['plan_scale', 'Scale & Teams & YC'],
        ['plan_teams', 'Scale & Teams & YC'],
        ['plan_yc', 'Scale & Teams & YC'],
        ['plan_boost', 'Boost & Startup & Pay-as-you-go paying'],
        ['plan_startup', 'Boost & Startup & Pay-as-you-go paying'],
        ['plan_paid', 'Boost & Startup & Pay-as-you-go paying'],
        ['plan_free', 'Free plan'],
        ['community', 'Community'],
        // Zendesk-import vocabulary (many imported tickets still carry these)
        ['plan_top20', 'Top 20'],
        ['plan_onboarding', 'Onboarding'],
        ['plan_teams_legacy', 'Scale & Teams & YC'],
        ['plan_pay-as-you-go_paying', 'Boost & Startup & Pay-as-you-go paying'],
        ['plan_pay-as-you-go', 'Boost & Startup & Pay-as-you-go paying'],
        ['plan_pay-as-you-go_free', 'Pay-as-you-go free'],
    ])('routes %s to %s', (tag, label) => {
        expect(planLabel([tag])).toBe(label)
    })

    it('takes the highest-priority group when several tags match', () => {
        expect(planLabel(['plan_free', 'plan_enterprise', 'churn_risk'])).toBe('Churn risk')
    })

    it('falls back to Triage for untagged or unmatched tickets', () => {
        expect(planLabel([])).toBe('Triage')
        expect(planLabel(undefined)).toBe('Triage')
        expect(planLabel(['team_replay', 'support_sme_analytics'])).toBe('Triage')
    })

    it('requires exact tag matches, not prefixes or substrings', () => {
        expect(planLabel(['plan_enterprise_trial'])).toBe('Triage')
        expect(planLabel(['community_forum'])).toBe('Triage')
    })
})

describe('planRank', () => {
    it('ranks follow the group order, untagged with Triage', () => {
        expect(planRank(['support_needs_triage'])).toBe(0)
        expect(planRank([])).toBe(0)
        expect(planRank(['community'])).toBe(PLAN_GROUPS.length - 1)
        expect(planRank(['churn_risk'])).toBeLessThan(planRank(['plan_enterprise']))
        expect(planRank(['plan_pay-as-you-go'])).toBeLessThan(planRank(['plan_pay-as-you-go_free']))
        expect(planRank(['plan_pay-as-you-go_free'])).toBeLessThan(planRank(['plan_free']))
    })
})
