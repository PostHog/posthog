import {
    IconBolt,
    IconBuilding,
    IconClock,
    IconCursor,
    IconDatabase,
    IconDecisionTree,
    IconDownload,
    IconGear,
    IconGraph,
    IconLlmAnalytics,
    IconLogomark,
    IconMessage,
    IconNotification,
    IconPassword,
    IconPeople,
    IconPieChart,
    IconPlaylist,
    IconRevert,
    IconRewindPlay,
    IconSampling,
    IconStack,
    IconTerminal,
    IconTestTube,
    IconToggle,
    IconUnlock,
    IconWarning,
} from '@posthog/icons'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { type AvailableOnboardingProducts } from '~/types'

const ICON_MAP: Record<string, React.ComponentType<{ className?: string; color?: string }>> = {
    IconBolt,
    IconBuilding,
    IconClock,
    IconCursor,
    IconDatabase,
    IconDecisionTree,
    IconDownload,
    IconGear,
    IconGraph,
    IconLlmAnalytics,
    IconLogomark,
    IconMessage,
    IconNotification,
    IconPassword,
    IconPeople,
    IconPieChart,
    IconPlaylist,
    IconRevert,
    IconRewindPlay,
    IconSampling,
    IconStack,
    IconTerminal,
    IconTestTube,
    IconToggle,
    IconUnlock,
    IconWarning,
}

export function getProductIcon(
    iconKey?: string | null,
    { iconColor, className }: { iconColor?: string; className?: string } = {}
): JSX.Element {
    const IconComponent = iconKey ? ICON_MAP[iconKey] : undefined
    if (IconComponent) {
        return <IconComponent className={className} color={iconColor} />
    }

    return <IconLogomark className={className} />
}

export function toSentenceCase(name: string): string {
    return name
        .split(' ')
        .map((word, i) => {
            if (i === 0) {
                return word
            }
            if (word === word.toUpperCase() && word.length <= 4) {
                return word
            }
            return word.toLowerCase()
        })
        .join(' ')
}

// This is the order we'll use to display the products in the onboarding
export const availableOnboardingProducts: AvailableOnboardingProducts = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        name: 'Product Analytics',
        description: 'Track events, trends, and user behavior',
        userCentricDescription: 'See what users do in your app',
        capabilities: ['Funnels & conversion tracking', 'Trend analysis & dashboards', 'User paths & retention'],
        icon: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        url: urls.insights(),
        scene: Scene.SavedInsights,
        setupEffort: 'low',
        socialProof: 'Used by 185K+ teams',
    },
    [ProductKey.WEB_ANALYTICS]: {
        name: 'Web Analytics',
        description: 'Measure traffic, engagement, and conversion metrics for your website',
        userCentricDescription: 'See where visitors come from and what they do',
        capabilities: ['Traffic sources & referrals', 'Page performance metrics', 'Conversion funnels'],
        icon: 'IconPieChart',
        iconColor: 'rgb(54 196 111)',
        url: urls.webAnalytics(),
        scene: Scene.WebAnalytics,
        setupEffort: 'automatic',
        socialProof: 'Used by 165K+ teams',
    },
    [ProductKey.SESSION_REPLAY]: {
        name: 'Session Replay',
        description: 'Watch recordings of user sessions to debug issues faster',
        userCentricDescription: 'Watch real users navigate your app',
        capabilities: ['Video playback of sessions', 'Console & network logs', 'Click & scroll heatmaps'],
        icon: 'IconRewindPlay',
        iconColor: 'rgb(247 165 1)',
        url: urls.replay(),
        scene: Scene.Replay,
        setupEffort: 'automatic',
        socialProof: 'Used by 160K+ teams',
    },
    [ProductKey.LLM_ANALYTICS]: {
        name: 'LLM Analytics',
        description: 'Monitor LLM usage, costs, and quality',
        userCentricDescription: 'Keep your AI costs down and quality up',
        capabilities: ['Cost tracking per model', 'Latency & error monitoring', 'Prompt & response evaluation'],
        icon: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        url: urls.llmAnalyticsDashboard(),
        scene: Scene.LLMAnalytics,
        setupEffort: 'low',
        socialProof: 'Used by 55K+ teams',
    },
    [ProductKey.DATA_WAREHOUSE]: {
        name: 'Data Warehouse',
        description: 'Query external data alongside your PostHog data',
        userCentricDescription: 'Bring in data from Stripe, Salesforce, and more',
        capabilities: ['Sync Stripe, Salesforce & more', 'SQL queries on all your data', 'Scheduled data imports'],
        icon: 'IconDatabase',
        iconColor: 'rgb(133 103 255)',
        breadcrumbsName: 'Data Warehouse',
        url: urls.sources(),
        scene: Scene.Sources,
        setupEffort: 'medium',
        socialProof: 'Used by 77K+ teams',
    },
    [ProductKey.FEATURE_FLAGS]: {
        name: 'Feature Flags',
        description: 'Ship features safely with gradual rollouts',
        userCentricDescription: 'Roll out changes to the right users',
        capabilities: ['Percentage & user-based rollouts', 'Multivariate flags', 'Instant rollbacks'],
        icon: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        breadcrumbsName: 'Feature Flags',
        url: urls.featureFlags(),
        scene: Scene.FeatureFlags,
        setupEffort: 'medium',
        socialProof: 'Used by 70K+ teams',
    },
    [ProductKey.EXPERIMENTS]: {
        name: 'Experiments',
        description: 'Test changes and measure what works',
        userCentricDescription: 'Find out which version converts better',
        capabilities: ['A/B & multivariate testing', 'Statistical significance tracking', 'Revenue & conversion goals'],
        icon: 'IconTestTube',
        iconColor: 'rgb(182 42 217)',
        breadcrumbsName: 'Experiments',
        url: urls.experiments(),
        scene: Scene.Experiments,
        setupEffort: 'medium',
        socialProof: 'Used by 64K+ teams',
    },
    [ProductKey.ERROR_TRACKING]: {
        name: 'Error Tracking',
        description: 'Catch and fix bugs before users complain',
        userCentricDescription: 'Catch and fix bugs before users complain',
        capabilities: ['Automatic exception capture', 'Stack traces & source maps', 'Issue grouping & assignment'],
        icon: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        url: urls.errorTracking(),
        scene: Scene.ErrorTracking,
        setupEffort: 'automatic',
        socialProof: 'Used by 83K+ teams',
    },
    [ProductKey.SURVEYS]: {
        name: 'Surveys',
        description: 'Ask users why they did what they did',
        userCentricDescription: 'Ask users what they think, right in your app',
        capabilities: ['In-app popup surveys', 'Targeting by user properties', 'NPS, CSAT & custom questions'],
        icon: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        url: urls.surveys(),
        scene: Scene.Surveys,
        setupEffort: 'low',
        socialProof: 'Used by 103K+ teams',
    },
    [ProductKey.WORKFLOWS]: {
        name: 'Workflows',
        description: 'Automate user communication and internal processes',
        userCentricDescription: 'Send the right message at the right time',
        capabilities: ['Event-triggered automations', 'Slack, email & webhook actions', 'User journey orchestration'],
        icon: 'IconGear',
        iconColor: 'var(--color-product-workflows-light)',
        url: urls.workflows(),
        scene: Scene.Workflows,
        setupEffort: 'medium',
        socialProof: 'Used by 3K+ teams',
    },
}
