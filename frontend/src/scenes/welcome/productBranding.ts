import { ComponentType, SVGProps } from 'react'

import {
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconLlmAnalytics,
    IconMessage,
    IconPieChart,
    IconRewindPlay,
    IconWarning,
} from '@posthog/icons'

export type IconElement = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>

export interface ProductBranding {
    label: string
    docsHref: string
    Icon: IconElement
    /** Brand color as space-separated RGB channels so we can use it in rgb() / alpha overlays. */
    rgb: string
}

// Lifted from frontend/src/scenes/onboarding/utils.tsx so each product shows its actual brand color.
export const PRODUCT_BRANDING: Record<string, ProductBranding> = {
    product_analytics: {
        label: 'Product analytics',
        docsHref: 'https://posthog.com/docs/product-analytics',
        Icon: IconGraph,
        rgb: '47 128 250',
    },
    web_analytics: {
        label: 'Web analytics',
        docsHref: 'https://posthog.com/docs/web-analytics',
        Icon: IconPieChart,
        rgb: '54 196 111',
    },
    session_replay: {
        label: 'Session replay',
        docsHref: 'https://posthog.com/docs/session-replay',
        Icon: IconRewindPlay,
        rgb: '247 165 1',
    },
    feature_flags: {
        label: 'Feature flags',
        docsHref: 'https://posthog.com/docs/feature-flags',
        Icon: IconFlag,
        rgb: '48 171 198',
    },
    experiments: {
        label: 'Experiments',
        docsHref: 'https://posthog.com/docs/experiments',
        Icon: IconFlask,
        rgb: '182 42 217',
    },
    surveys: {
        label: 'Surveys',
        docsHref: 'https://posthog.com/docs/surveys',
        Icon: IconMessage,
        rgb: '243 84 84',
    },
    error_tracking: {
        label: 'Error tracking',
        docsHref: 'https://posthog.com/docs/error-tracking',
        Icon: IconWarning,
        rgb: '235 157 42',
    },
    data_warehouse: {
        label: 'Data warehouse',
        docsHref: 'https://posthog.com/docs/data-warehouse',
        Icon: IconDatabase,
        rgb: '133 103 255',
    },
    llm_analytics: {
        label: 'LLM analytics',
        docsHref: 'https://posthog.com/docs/ai-engineering/llm-analytics',
        Icon: IconLlmAnalytics,
        rgb: '182 42 217',
    },
}

export const FALLBACK_BRANDING: ProductBranding = {
    label: '',
    docsHref: 'https://posthog.com/docs',
    Icon: IconDashboard,
    rgb: '107 114 128', // neutral gray
}

/** Map ActivityLog scope strings to the product they belong to for branding purposes. */
export const SCOPE_TO_PRODUCT: Record<string, string> = {
    Insight: 'product_analytics',
    Dashboard: 'product_analytics',
    Notebook: 'product_analytics',
    Experiment: 'experiments',
    FeatureFlag: 'feature_flags',
    Survey: 'surveys',
}

/** Verbs used in the activity feed, keyed by scope OR the scope.activity pair for specificity. */
export const SCOPE_VERBS: Record<string, string> = {
    // Defaults per scope (used when the activity verb is generic or unknown)
    Insight: 'updated an insight',
    Dashboard: 'updated a dashboard',
    Notebook: 'updated a notebook',
    Experiment: 'updated an experiment',
    FeatureFlag: 'updated a feature flag',
    Survey: 'updated a survey',
    // More specific per-activity overrides
    'Insight.created': 'created an insight',
    'Insight.deleted': 'deleted an insight',
    'Dashboard.created': 'created a dashboard',
    'Dashboard.deleted': 'deleted a dashboard',
    'Notebook.created': 'wrote a notebook',
    'Notebook.deleted': 'deleted a notebook',
    'Experiment.created': 'created an experiment',
    'Experiment.deleted': 'deleted an experiment',
    'FeatureFlag.created': 'created a feature flag',
    'FeatureFlag.deleted': 'deleted a feature flag',
    'Survey.created': 'created a survey',
    'Survey.deleted': 'deleted a survey',
}

export function brandingForScope(type: string): { branding: ProductBranding; verb: string } {
    const [scope] = type.split('.')
    const productKey = SCOPE_TO_PRODUCT[scope]
    // Prefer the specific scope.activity verb; fall back to the scope default.
    const verb = SCOPE_VERBS[type] ?? SCOPE_VERBS[scope] ?? 'made a change'
    return {
        branding: (productKey && PRODUCT_BRANDING[productKey]) || FALLBACK_BRANDING,
        verb,
    }
}

export function brandingForProduct(productKey: string): ProductBranding {
    return PRODUCT_BRANDING[productKey] ?? { ...FALLBACK_BRANDING, label: productKey.replace(/_/g, ' ') }
}
