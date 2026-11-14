import { FEATURE_FLAGS } from 'lib/constants'

import { AvailableFeature } from '~/types'

type AvailableFeatureChecker = (feature: AvailableFeature) => boolean

interface FeaturePreviewWarning {
    /** Returns the warning to display for a feature, or null if none should show. */
    resolve: (hasAvailableFeature: AvailableFeatureChecker) => React.ReactNode | null
}

/**
 * Per-flag warnings shown on the early-access card. Add an entry here to surface a warning
 * for a specific preview without touching the FeaturePreview component itself.
 */
export const FEATURE_PREVIEW_WARNINGS: Record<string, FeaturePreviewWarning> = {
    [FEATURE_FLAGS.FEATURE_FLAG_NOTIFICATIONS]: {
        resolve: (hasAvailableFeature) =>
            hasAvailableFeature(AvailableFeature.AUDIT_LOGS)
                ? null
                : 'This feature requires the Enterprise plan or the Scale add-on. Enabling the preview will not unlock it on your current plan.',
    },
}

export const hasPosthogJsFailedToLoadFeaturePreviews = (): boolean =>
    !!window.POSTHOG_GLOBAL_ERRORS?.onFeatureFlagsLoadError
