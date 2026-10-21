import { IconBolt, IconCursorClick, IconFlask, IconPieChart, IconSearch, IconToggle } from '@posthog/icons'

import { urls } from '~/toolbar/urls'
import { AvailableFeature } from '~/types'

import type { PageToolbarMode } from './pageToolbarBridge'

export type PageToolMode = Exclude<PageToolbarMode, 'none'>

// pinned: sent as the `feature` property of `toolbar extension feature opened`
export type ExtensionFeatureKey = 'heatmaps' | 'actions' | 'feature-flags' | 'experiments' | 'web-vitals'

export interface PageToolDefinition {
    /** Missing for a tool the panel only links to in PostHog. */
    mode?: PageToolMode
    label: string
    description: string
    icon: JSX.Element
    /** The tool's page in PostHog. */
    feature?: { key: ExtensionFeatureKey; path: string }
    /** The paid feature the floating toolbar gates this tool on. */
    gate?: AvailableFeature
}

/** The floating toolbar's buttons, in toolbar order, with its "More" menu last. */
export const PAGE_TOOLS: PageToolDefinition[] = [
    {
        mode: 'inspect',
        label: 'Inspect',
        description: "Hover the page to see each element's selector, clicks and actions",
        icon: <IconSearch />,
    },
    {
        mode: 'heatmap',
        label: 'Heatmap',
        description: 'Show where people click and how far they scroll',
        icon: <IconCursorClick />,
        feature: { key: 'heatmaps', path: urls.heatmaps() },
        gate: AvailableFeature.TOOLBAR_HEATMAPS,
    },
    {
        label: 'Actions',
        description: 'Create and edit actions from elements on the page',
        icon: <IconBolt />,
        feature: { key: 'actions', path: urls.actions() },
    },
    {
        label: 'Feature flags',
        description: 'Override feature flags on this page',
        icon: <IconToggle />,
        feature: { key: 'feature-flags', path: urls.featureFlags() },
    },
    {
        label: 'Web vitals',
        description: 'Check how fast this page loads',
        icon: <IconPieChart />,
        feature: { key: 'web-vitals', path: urls.webAnalyticsWebVitals() },
    },
    {
        label: 'Experiments',
        description: 'Build no-code web experiments and preview their variants on the page',
        icon: <IconFlask />,
        feature: { key: 'experiments', path: urls.experiments() },
    },
]
