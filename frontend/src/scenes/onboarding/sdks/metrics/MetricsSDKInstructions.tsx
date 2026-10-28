import { OpenTelemetryInstallation } from '@posthog/shared-onboarding/metrics'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Metrics arrives over OTLP, either from the scrape agent or straight from an OTel
// exporter. Both paths are steps of the one entry, so wizardIntegrationName is
// omitted: the posthog-wizard doesn't set up OTLP metrics.
const MetricsOpenTelemetryInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OpenTelemetryInstallation,
})

export const MetricsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENTELEMETRY]: MetricsOpenTelemetryInstructionsWrapper,
}
