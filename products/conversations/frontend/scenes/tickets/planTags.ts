// The customer's plan tier, derived from ticket tags — the support team's
// triage ladder. Group order IS the priority order (Triage first, Community
// last): a ticket takes the highest-priority group with a matching tag, and
// tickets with no matching tag fall into Triage (they still need routing).
//
// Tag vocabulary sources, all kept so every era of ticket groups correctly:
// - The "Customer and account tags" section of
//   https://posthog.com/handbook/support/posthog-support (source of truth)
// - The live "Support:: SLA:: identify plan types and set NRT SLAs" workflow
//   (top_20, plan_teams, plan_paid, new_customer_onboarding, ...)
// - The Zendesk import (plan_top20, plan_teams_legacy, plan_pay-as-you-go*,
//   ... — surveyed against the zendesk.tickets warehouse table, 2026-07-20)
//
// Matching is exact (no prefixes): plan_enterprise_trial is NOT Enterprise.

export interface PlanGroup {
    label: string
    tags: string[]
}

export const PLAN_GROUPS: PlanGroup[] = [
    { label: 'Triage', tags: ['support_needs_triage'] },
    { label: 'Churn risk', tags: ['churn_risk'] },
    { label: 'Top 20', tags: ['plan_top20', 'top_20'] },
    {
        label: 'Enterprise',
        tags: [
            'plan_enterprise',
            'goodwill_enterprise',
            'unknown_slack_default_enterprise',
            'unknown_msteams_default_enterprise',
        ],
    },
    { label: 'Onboarding', tags: ['plan_onboarding', 'new_customer_onboarding'] },
    { label: 'Scale & Teams & YC', tags: ['plan_scale', 'plan_teams_legacy', 'plan_teams', 'plan_yc'] },
    {
        label: 'Boost & Startup & Pay-as-you-go paying',
        tags: ['plan_boost', 'plan_startup', 'plan_pay-as-you-go_paying', 'plan_pay-as-you-go', 'plan_paid'],
    },
    { label: 'Pay-as-you-go free', tags: ['plan_pay-as-you-go_free'] },
    { label: 'Free plan', tags: ['plan_free'] },
    { label: 'Community', tags: ['community'] },
]

const TAG_RANK = new Map<string, number>(PLAN_GROUPS.flatMap((group, rank) => group.tags.map((tag) => [tag, rank])))

/** Index into PLAN_GROUPS of the ticket's group — the best (lowest) rank
 *  across its tags, or Triage (0) when none match. */
export function planRank(tags: string[] | undefined): number {
    let best = Number.POSITIVE_INFINITY
    for (const tag of tags ?? []) {
        const rank = TAG_RANK.get(tag)
        if (rank !== undefined && rank < best) {
            best = rank
        }
    }
    return best === Number.POSITIVE_INFINITY ? 0 : best
}

export function planLabel(tags: string[] | undefined): string {
    return PLAN_GROUPS[planRank(tags)].label
}
