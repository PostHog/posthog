import {
    AIObservabilitySDKInstructions,
    AIObservabilitySDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/ai-observability/AIObservabilitySDKInstructions'
import {
    ErrorTrackingSDKDocsLinkOverrides,
    ErrorTrackingSDKInstructions,
} from 'scenes/onboarding/legacy/sdks/error-tracking/ErrorTrackingSDKInstructions'
import { ExperimentsSDKInstructions } from 'scenes/onboarding/legacy/sdks/experiments/ExperimentsSDKInstructions'
import { FeatureFlagsSDKInstructions } from 'scenes/onboarding/legacy/sdks/feature-flags/FeatureFlagsSDKInstructions'
import { LogsSDKInstructions } from 'scenes/onboarding/legacy/sdks/logs/LogsSDKInstructions'
import { ProductAnalyticsSDKInstructions } from 'scenes/onboarding/legacy/sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { SessionReplaySDKInstructions } from 'scenes/onboarding/legacy/sdks/session-replay/SessionReplaySDKInstructions'
import { SurveysSDKInstructions } from 'scenes/onboarding/legacy/sdks/surveys/SurveysSDKInstructions'
import { WebAnalyticsSDKInstructions } from 'scenes/onboarding/legacy/sdks/web-analytics/WebAnalyticsSDKInstructions'

import { ProductKey } from '~/queries/schema/schema-general'
import { SDKDocsLinkOverrides, SDKInstructionsMap, SDKTagOverrides } from '~/types'

export const PRODUCT_SDK_SETUP: Partial<
    Record<
        ProductKey,
        {
            instructionsMap: SDKInstructionsMap
            docsLinkOverrides?: SDKDocsLinkOverrides
            tagOverrides?: SDKTagOverrides
            verifyingName?: string
        }
    >
> = {
    [ProductKey.PRODUCT_ANALYTICS]: { instructionsMap: ProductAnalyticsSDKInstructions },
    [ProductKey.WEB_ANALYTICS]: { instructionsMap: WebAnalyticsSDKInstructions },
    [ProductKey.SESSION_REPLAY]: { instructionsMap: SessionReplaySDKInstructions },
    [ProductKey.ERROR_TRACKING]: {
        instructionsMap: ErrorTrackingSDKInstructions,
        docsLinkOverrides: ErrorTrackingSDKDocsLinkOverrides,
    },
    [ProductKey.SURVEYS]: { instructionsMap: SurveysSDKInstructions },
    [ProductKey.FEATURE_FLAGS]: { instructionsMap: FeatureFlagsSDKInstructions },
    [ProductKey.EXPERIMENTS]: { instructionsMap: ExperimentsSDKInstructions },
    [ProductKey.AI_OBSERVABILITY]: {
        instructionsMap: AIObservabilitySDKInstructions,
        tagOverrides: AIObservabilitySDKTagOverrides,
        verifyingName: 'LLM generation',
    },
    [ProductKey.LOGS]: { instructionsMap: LogsSDKInstructions },
}
