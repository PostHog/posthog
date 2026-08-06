import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { UserRole } from '~/types'

export interface AIReportDefinition {
    key: string
    headline: string
    lead: string
    title: string
    /**
     * Handed to the AI-subscription planner, which writes and runs its own HogQL. Names concrete
     * event properties so it queries the right ones rather than guessing, and tells it to say so
     * plainly when the project doesn't have the data yet (most subscribers set this up before
     * they've instrumented anything).
     */
    prompt: string
}

// Founders and engineers get the same report: per the role mapping decision, both care most
// about whether the business is growing, not about a role-specific slice.
const REVENUE_SIGNUPS: AIReportDefinition = {
    key: 'revenue-signups',
    headline: 'Revenue and sign-up growth',
    lead: 'New sign-ups and revenue movement this week, compared with last week.',
    title: 'Weekly revenue and sign-up growth',
    prompt: [
        'Summarize business growth for the last 7 days compared with the previous 7 days.',
        'Count new sign-ups: persons whose first event ever was in the last 7 days, plus any',
        'explicit sign-up events if the project has them (event names containing "sign" or "register").',
        'If the project has revenue or payment events (names containing "purchase", "payment",',
        '"subscription" or "checkout"), report their volume and unique payers week over week.',
        'If none exist, say so plainly and skip revenue rather than inventing numbers.',
        'Close with the single most important growth change and a plausible reason for it.',
    ].join(' '),
}

const GENERIC_USAGE_DIGEST: AIReportDefinition = {
    key: 'usage-digest',
    headline: 'How your product was used',
    lead: 'Active users, top pages and top events for the week, with what moved.',
    title: 'Weekly product usage digest',
    prompt: [
        'Summarize product usage for the last 7 days using this project’s events.',
        'Report weekly active users (unique persons), total events, and $pageview volume,',
        'each compared with the previous 7 days.',
        'List the top 10 pages by $pageview count using the $pathname property,',
        'and the top custom events (exclude event names starting with $).',
        'Call out anything that moved more than 20% week over week,',
        'and finish with the single most notable change and a plausible reason for it.',
        'If the project has little or no data yet, say so plainly instead of inventing numbers.',
    ].join(' '),
}

export const AI_REPORTS_BY_ROLE: Record<UserRole, AIReportDefinition> = {
    [UserRole.Leadership]: {
        key: 'aarrr-funnel',
        headline: 'Your funnel at a glance',
        lead: 'Acquisition, activation, retention, referral and revenue for the week.',
        title: 'Weekly funnel summary',
        prompt: [
            'Produce an AARRR summary for the last 7 days, each stage compared with the previous 7 days.',
            'Acquisition: unique persons with a $pageview, and the top $referring_domain values.',
            'Activation: persons whose first event ever was this week who then performed any custom',
            'event (names not starting with $).',
            'Retention: share of persons active in the previous 7 days who returned this week.',
            'Referral: events or UTM parameters (utm_source on $pageview) suggesting shared or referred traffic.',
            'Revenue: volume of purchase, payment or subscription events if the project has them.',
            'For any stage where the project has no data yet, say so plainly rather than inventing numbers.',
            'End with the weakest stage this week and one suggestion to investigate it.',
        ].join(' '),
    },
    [UserRole.Marketing]: {
        key: 'traffic-pages',
        headline: 'What people visited and how traffic changed',
        lead: 'Most popular pages this week and shifts in where visitors come from.',
        title: 'Weekly pages and traffic changes',
        prompt: [
            'Report on web traffic for the last 7 days compared with the previous 7 days using $pageview events.',
            'List the top 10 pages by $pathname with unique visitors and week-over-week change.',
            'Break down traffic sources using $referring_domain and utm_source, and call out any source',
            'that moved more than 20%.',
            'Note changes in bounce-like behavior: persons with exactly one $pageview in a session.',
            'If the project has little or no traffic data yet, say so plainly instead of inventing numbers.',
            'Finish with the most notable traffic shift and a plausible cause.',
        ].join(' '),
    },
    [UserRole.Sales]: {
        key: 'new-signups',
        headline: 'Who signed up this week',
        lead: 'New sign-ups this week, where they came from, and how the pace is trending.',
        title: 'Weekly new sign-ups',
        prompt: [
            'Report new sign-ups for the last 7 days compared with the previous 7 days.',
            'Count persons whose first event ever was in the last 7 days, plus explicit sign-up events',
            'if the project has them (event names containing "sign" or "register").',
            'Show sign-ups per day to reveal the trend, and the top acquisition sources for new persons',
            'using $referring_domain and utm_source on their first $pageview.',
            'If the project has no sign-up data yet, say so plainly instead of inventing numbers.',
            'Close with whether the sign-up pace is accelerating or slowing and by how much.',
        ].join(' '),
    },
    [UserRole.Founder]: REVENUE_SIGNUPS,
    [UserRole.Engineering]: REVENUE_SIGNUPS,
    [UserRole.Product]: {
        key: 'feature-retention',
        headline: 'Feature usage and retention',
        lead: 'Which features got used this week and whether users are coming back.',
        title: 'Weekly feature usage and retention',
        prompt: [
            'Summarize feature usage for the last 7 days compared with the previous 7 days.',
            'Rank the top 10 custom events (names not starting with $) by unique persons, with change.',
            'Report retention: share of persons active in the previous 7 days who returned this week,',
            'and the same for persons whose first event ever was in the previous week.',
            'Call out any feature whose unique users moved more than 20% week over week.',
            'If the project has little or no data yet, say so plainly instead of inventing numbers.',
            'End with the feature most worth attention this week and why.',
        ].join(' '),
    },
    [UserRole.Data]: {
        key: 'events-volume',
        headline: 'Top events and volume changes',
        lead: 'The biggest event streams and what moved week over week.',
        title: 'Weekly event volume changes',
        prompt: [
            'Compare event volume for the last 7 days against the previous 7 days for every event name',
            'in this project, excluding internal events starting with $ (but keep $pageview).',
            'Rank the top 10 events by volume, and separately the five fastest-growing and five',
            'fastest-declining by relative change, ignoring events under 100 occurrences in both windows.',
            'For each big mover, note whether unique persons moved with volume, since volume rising on',
            'flat users means heavier use rather than more reach.',
            'If the project has little or no data yet, say so plainly instead of inventing numbers.',
            'Close with anything that looks like an instrumentation problem, such as an event that',
            'vanished or spiked.',
        ].join(' '),
    },
    [UserRole.Student]: GENERIC_USAGE_DIGEST,
    [UserRole.Other]: GENERIC_USAGE_DIGEST,
}

/** An unset or unrecognized role gets the generic digest, so the step never dead-ends on role. */
export function reportForRole(role: string | null | undefined): AIReportDefinition {
    return AI_REPORTS_BY_ROLE[role as UserRole] ?? GENERIC_USAGE_DIGEST
}

export type AIReportsExperimentArm = 'control' | 'test'

/**
 * The user's experiment arm, or null when they are not enrolled: an unset/boolean flag value (not
 * rolled out, targeting excludes them, flags not loaded yet) must NOT be collapsed into `control`,
 * or never-enrolled users pollute the control cohort and bias the readout toward "no effect".
 */
export function resolveAIReportsArm(featureFlags: FeatureFlagsSet): AIReportsExperimentArm | null {
    const value = featureFlags[FEATURE_FLAGS.ONBOARDING_AI_REPORTS]
    return value === 'test' || value === 'control' ? value : null
}
