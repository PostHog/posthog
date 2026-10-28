import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'

import { urls } from '~/toolbar/urls'
import { AvailableFeature } from '~/types'

// pinned: sent as the `feature` property of `toolbar extension feature opened`
export type ExtensionFeatureKey = 'heatmaps' | 'actions' | 'feature-flags' | 'experiments' | 'web-vitals'

export interface ExtensionFeatureEntryPoint {
    key: ExtensionFeatureKey
    label: string
    description: string
    /** PostHog app path, relative to the project. */
    path: string
    /** The plan gate the floating toolbar applies to this feature. */
    gate?: { feature: AvailableFeature; rolloutFlag: FeatureFlagKey }
}

/** The floating toolbar's menus, in toolbar order. */
export const EXTENSION_FEATURE_ENTRY_POINTS: ExtensionFeatureEntryPoint[] = [
    {
        key: 'heatmaps',
        label: 'Heatmaps',
        description: 'See where people click and how far they scroll',
        path: urls.heatmaps(),
        gate: { feature: AvailableFeature.TOOLBAR_HEATMAPS, rolloutFlag: FEATURE_FLAGS.TOOLBAR_PAID_HEATMAPS },
    },
    {
        key: 'actions',
        label: 'Actions',
        description: 'Define actions from elements on your pages',
        path: urls.actions(),
    },
    {
        key: 'feature-flags',
        label: 'Feature flags',
        description: 'Review and override flags',
        path: urls.featureFlags(),
    },
    {
        key: 'web-vitals',
        label: 'Web vitals',
        description: 'Check page load performance',
        path: urls.webAnalyticsWebVitals(),
    },
    {
        key: 'experiments',
        label: 'Experiments',
        description: 'Create and review web experiments',
        path: urls.experiments(),
    },
]
