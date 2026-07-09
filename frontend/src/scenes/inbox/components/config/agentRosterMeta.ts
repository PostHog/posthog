import { FEATURE_FLAGS } from 'lib/constants'

import { DataWarehouseSource } from '../../signalSourcesLogic'
import { SignalSourceProduct } from '../../types'

/**
 * Stable string keys for the agent roster, aligned with the source-product
 * strings the backend uses. These drive icon lookup via `getSourceProductMeta`
 * and the per-source wiring in `AgentsRoster`.
 */
export type AgentRosterSource =
    | 'error_tracking'
    | 'conversations'
    | 'session_replay'
    | 'llm_analytics'
    | 'github'
    | 'linear'
    | 'zendesk'
    | 'pganalyze'
    | 'engineering_analytics'

export interface AgentRosterDefinition {
    source: AgentRosterSource
    /** Key into `SOURCE_PRODUCT_META` for the icon tile. */
    sourceProduct: SignalSourceProduct
    label: string
    description: string
    docsUrl?: string
    docsLabel?: string
    alpha?: boolean
    /** Show this entry only while the given feature flag is enabled (alpha rollouts). */
    flag?: string
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
                sourceProduct: SignalSourceProduct.ErrorTracking,
                label: 'Error tracking',
                description: 'Bugs surfaced as new errors, regressions, and spikes.',
                docsUrl: 'https://posthog.com/docs/error-tracking',
                docsLabel: 'Error tracking',
            },
            {
                source: 'conversations',
                sourceProduct: SignalSourceProduct.Conversations,
                label: 'Support',
                description: 'Problems customers raise in support.',
                docsUrl: 'https://posthog.com/docs/support',
                docsLabel: 'Support',
            },
            {
                source: 'session_replay',
                sourceProduct: SignalSourceProduct.SessionReplay,
                label: 'Session replay',
                description: 'UX problems found in session recordings.',
                docsUrl: 'https://posthog.com/docs/session-replay',
                docsLabel: 'Session replay',
                alpha: true,
            },
            {
                source: 'llm_analytics',
                sourceProduct: SignalSourceProduct.LlmAnalytics,
                label: 'AI observability',
                description: 'Findings from evaluation reports on your LLM traffic.',
                docsUrl: 'https://posthog.com/docs/ai-evals/evaluations',
                docsLabel: 'AI observability',
            },
        ],
    },
    {
        label: 'Connected tools',
        agents: [
            {
                source: 'github',
                sourceProduct: SignalSourceProduct.Github,
                label: 'GitHub Issues',
                description: 'Issues filed in GitHub.',
                dataWarehouseSource: 'Github',
            },
            {
                source: 'engineering_analytics',
                sourceProduct: SignalSourceProduct.EngineeringAnalytics,
                label: 'GitHub CI',
                description: 'Flaky checks, broken master, and slowing workflows in GitHub Actions.',
                dataWarehouseSource: 'Github',
                alpha: true,
                flag: FEATURE_FLAGS.ENGINEERING_ANALYTICS,
            },
            {
                source: 'linear',
                sourceProduct: SignalSourceProduct.Linear,
                label: 'Linear',
                description: 'Issues tracked in Linear.',
                dataWarehouseSource: 'Linear',
            },
            {
                source: 'zendesk',
                sourceProduct: SignalSourceProduct.Zendesk,
                label: 'Zendesk',
                description: 'Incoming Zendesk tickets.',
                dataWarehouseSource: 'Zendesk',
            },
            {
                source: 'pganalyze',
                sourceProduct: SignalSourceProduct.Pganalyze,
                label: 'pganalyze',
                description: 'Postgres performance problems – slow queries and bad indexes.',
                dataWarehouseSource: 'PgAnalyze',
            },
        ],
    },
]
