// PROTOTYPE — throwaway mock data for the property usage variants. Pick a scenario with `?scenario=`.
import { dayjs } from 'lib/dayjs'

export type UsageRole = 'filter' | 'breakdown' | 'math' | 'sql'

// Where each figure would come from. "pr" = already provided by PR 82610, "new" = needs more backend work.
export type DataSource = 'pr' | 'new'

export interface UsagePerson {
    first_name: string
    email: string
    queries: number
    lastQueriedAt: string
}

export interface UsageInsight {
    short_id: string
    name: string
    kind: 'Trends' | 'Funnel' | 'Retention' | 'SQL' | 'Paths'
    roles: UsageRole[]
    views30d: number
    lastViewedAt: string | null
    dashboards: string[]
    createdBy: string
}

export interface UsageOtherReference {
    kind: 'Feature flag' | 'Cohort' | 'Experiment' | 'Survey'
    name: string
    active: boolean
}

export interface PropertyUsage {
    scenario: string
    queries30d: number
    queriesPrior30d: number
    daily: number[]
    lastQueriedAt: string | null
    lastIngestedAt: string | null
    seenOnEvents: { name: string; share: number }[]
    people: UsagePerson[]
    insights: UsageInsight[]
    otherReferences: UsageOtherReference[]
}

const ago = (amount: number, unit: 'hour' | 'day'): string => dayjs().subtract(amount, unit).toISOString()

function dailySeries(total: number, seed: number, decay = 0): number[] {
    // Deterministic wobble so stories render the same every time
    const weights = Array.from({ length: 30 }, (_, i) => {
        const weekday = (i + seed) % 7 < 5 ? 1 : 0.35
        const wobble = 0.6 + ((Math.sin(i * 1.7 + seed) + 1) / 2) * 0.8
        return weekday * wobble * (1 + decay * (i / 29))
    })
    const sum = weights.reduce((a, b) => a + b, 0)
    return weights.map((w) => Math.round((w / sum) * total))
}

const HEAVY: PropertyUsage = {
    scenario: 'heavy',
    queries30d: 4821,
    queriesPrior30d: 3907,
    daily: dailySeries(4821, 3, 0.4),
    lastQueriedAt: ago(1, 'hour'),
    lastIngestedAt: ago(0, 'hour'),
    seenOnEvents: [
        { name: '$pageview', share: 0.62 },
        { name: 'checkout_started', share: 0.21 },
        { name: 'order_placed', share: 0.11 },
        { name: '$autocapture', share: 0.06 },
    ],
    people: [
        { first_name: 'Ada', email: 'ada@example.com', queries: 1912, lastQueriedAt: ago(1, 'hour') },
        { first_name: 'Ben', email: 'ben@example.com', queries: 1240, lastQueriedAt: ago(3, 'hour') },
        { first_name: 'Chiara', email: 'chiara@example.com', queries: 806, lastQueriedAt: ago(1, 'day') },
        { first_name: 'Dev', email: 'dev@example.com', queries: 512, lastQueriedAt: ago(2, 'day') },
        { first_name: 'Elif', email: 'elif@example.com', queries: 233, lastQueriedAt: ago(6, 'day') },
        { first_name: 'Finn', email: 'finn@example.com', queries: 118, lastQueriedAt: ago(19, 'day') },
    ],
    insights: [
        {
            short_id: 'aB12cD34',
            name: 'Checkout conversion by plan',
            kind: 'Funnel',
            roles: ['breakdown'],
            views30d: 1630,
            lastViewedAt: ago(1, 'hour'),
            dashboards: ['Revenue weekly', 'Exec overview'],
            createdBy: 'Ada',
        },
        {
            short_id: 'eF56gH78',
            name: 'MRR by plan',
            kind: 'Trends',
            roles: ['breakdown', 'filter'],
            views30d: 1104,
            lastViewedAt: ago(3, 'hour'),
            dashboards: ['Revenue weekly'],
            createdBy: 'Ben',
        },
        {
            short_id: 'iJ90kL12',
            name: 'Enterprise accounts active this week',
            kind: 'Trends',
            roles: ['filter'],
            views30d: 702,
            lastViewedAt: ago(1, 'day'),
            dashboards: ['Sales pipeline'],
            createdBy: 'Chiara',
        },
        {
            short_id: 'mN34oP56',
            name: 'Plan upgrades (SQL)',
            kind: 'SQL',
            roles: ['sql'],
            views30d: 488,
            lastViewedAt: ago(2, 'day'),
            dashboards: [],
            createdBy: 'Dev',
        },
        {
            short_id: 'qR78sT90',
            name: 'Retention for paid plans',
            kind: 'Retention',
            roles: ['filter'],
            views30d: 61,
            lastViewedAt: ago(9, 'day'),
            dashboards: [],
            createdBy: 'Elif',
        },
        {
            short_id: 'uV12wX34',
            name: 'Old pricing experiment readout',
            kind: 'Trends',
            roles: ['breakdown'],
            views30d: 0,
            lastViewedAt: ago(140, 'day'),
            dashboards: [],
            createdBy: 'Finn',
        },
    ],
    otherReferences: [
        { kind: 'Feature flag', name: 'enterprise-sso', active: true },
        { kind: 'Cohort', name: 'Paying customers', active: true },
        { kind: 'Experiment', name: 'Annual plan nudge', active: false },
    ],
}

const LIGHT: PropertyUsage = {
    scenario: 'light',
    queries30d: 37,
    queriesPrior30d: 212,
    daily: dailySeries(37, 1, -0.9),
    lastQueriedAt: ago(11, 'day'),
    lastIngestedAt: ago(2, 'hour'),
    seenOnEvents: [{ name: 'signup_completed', share: 1 }],
    people: [{ first_name: 'Finn', email: 'finn@example.com', queries: 37, lastQueriedAt: ago(11, 'day') }],
    insights: [
        {
            short_id: 'yZ56aB78',
            name: 'Signups by referral source',
            kind: 'Trends',
            roles: ['breakdown'],
            views30d: 37,
            lastViewedAt: ago(11, 'day'),
            dashboards: [],
            createdBy: 'Finn',
        },
    ],
    otherReferences: [],
}

const DEAD: PropertyUsage = {
    scenario: 'dead',
    queries30d: 0,
    queriesPrior30d: 0,
    daily: Array(30).fill(0),
    lastQueriedAt: null,
    lastIngestedAt: ago(45, 'day'),
    seenOnEvents: [{ name: 'legacy_import', share: 1 }],
    people: [],
    insights: [],
    otherReferences: [],
}

export const USAGE_SCENARIOS = ['heavy', 'light', 'dead']

export function getMockPropertyUsage(scenario: string): PropertyUsage {
    return scenario === 'light' ? LIGHT : scenario === 'dead' ? DEAD : HEAVY
}

export const ROLE_LABELS: Record<UsageRole, string> = {
    filter: 'Filter',
    breakdown: 'Breakdown',
    math: 'Aggregation',
    sql: 'SQL',
}
