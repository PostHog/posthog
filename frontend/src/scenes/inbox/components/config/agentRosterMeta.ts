import { SignalSourceProduct } from '~/queries/schema/schema-signals'

import { DataWarehouseSource } from '../../signalSourcesLogic'

/**
 * Stable string keys for the agent roster, aligned with the source-product
 * strings the backend uses. These drive icon lookup via `getSourceProductMeta`
 * and the per-source wiring in `AgentsRoster`.
 */
export type AgentRosterSource =
    | 'error_tracking'
    | 'conversations'
    | 'session_replay'
    | 'github'
    | 'linear'
    | 'zendesk'
    | 'pganalyze'

export interface AgentRosterDefinition {
    source: AgentRosterSource
    /** Key into `SOURCE_PRODUCT_META` for the icon tile. */
    sourceProduct: SignalSourceProduct
    label: string
    description: string
    docsUrl?: string
    docsLabel?: string
    alpha?: boolean
    /**
     * For data-warehouse-backed sources, the wizard product passed to
     * `initiateDataWarehouseSourceToggle`. Absent for native PostHog sources
     * (error tracking, session replay).
     */
    dataWarehouseSource?: DataWarehouseSource
}

export interface AgentRosterGroup {
    label: string
    agents: AgentRosterDefinition[]
}

export const AGENT_ROSTER_GROUPS: AgentRosterGroup[] = [
    {
        label: 'PostHog data',
        agents: [
            {
                source: 'error_tracking',
                sourceProduct: SignalSourceProduct.ERROR_TRACKING,
                label: 'Error tracking',
                description: 'Bugs surfaced as new errors, regressions, and spikes.',
                docsUrl: 'https://posthog.com/docs/error-tracking',
                docsLabel: 'Error tracking',
            },
            {
                source: 'conversations',
                sourceProduct: SignalSourceProduct.CONVERSATIONS,
                label: 'Support',
                description: 'Problems customers raise in support.',
                docsUrl: 'https://posthog.com/docs/support',
                docsLabel: 'Support',
            },
            {
                source: 'session_replay',
                sourceProduct: SignalSourceProduct.SESSION_REPLAY,
                label: 'Session replay',
                description: 'UX problems found in session recordings.',
                docsUrl: 'https://posthog.com/docs/session-replay',
                docsLabel: 'Session replay',
                alpha: true,
            },
        ],
    },
    {
        label: 'Connected tools',
        agents: [
            {
                source: 'github',
                sourceProduct: SignalSourceProduct.GITHUB,
                label: 'GitHub Issues',
                description: 'Issues filed in GitHub.',
                dataWarehouseSource: 'Github',
            },
            {
                source: 'linear',
                sourceProduct: SignalSourceProduct.LINEAR,
                label: 'Linear',
                description: 'Issues tracked in Linear.',
                dataWarehouseSource: 'Linear',
            },
            {
                source: 'zendesk',
                sourceProduct: SignalSourceProduct.ZENDESK,
                label: 'Zendesk',
                description: 'Incoming Zendesk tickets.',
                dataWarehouseSource: 'Zendesk',
            },
            {
                source: 'pganalyze',
                sourceProduct: SignalSourceProduct.PGANALYZE,
                label: 'pganalyze',
                description: 'Postgres performance problems – slow queries and bad indexes.',
                dataWarehouseSource: 'PgAnalyze',
            },
        ],
    },
]
