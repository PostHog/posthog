import React from 'react'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

import SetupWizardBanner from '../sdk-install-instructions/components/SetupWizardBanner'
import { AdvertiseMobileReplay, AdvertiseMobileReplayContext } from '../session-replay/SessionReplaySDKInstructions'

/**
 * Helper to create wrapped instruction components without recreating snippets on every render.
 * Used by product-analytics, feature-flags, experiments, and llm-analytics onboarding flows.
 */
export function withOnboardingDocsWrapper(
    Installation: React.ComponentType<any>,
    snippets?: Record<string, React.ComponentType<any>>,
    wizardIntegrationName?: string
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <>
                {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                <OnboardingDocsContentWrapper snippets={snippets}>
                    <Installation />
                </OnboardingDocsContentWrapper>
            </>
        )
    }
}

/**
 * Helper to create components with Installation + AdvertiseMobileReplay (for mobile SDKs).
 * Used for Android, iOS, React Native, and Flutter SDKs.
 */
export function withMobileReplay(
    Installation: React.ComponentType<any>,
    sdkKey: SDKKey,
    context: AdvertiseMobileReplayContext,
    snippets?: Record<string, React.ComponentType<any>>,
    wizardIntegrationName?: string
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <>
                {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                <OnboardingDocsContentWrapper snippets={snippets}>
                    <Installation />
                    <AdvertiseMobileReplay context={context} sdkKey={sdkKey} />
                </OnboardingDocsContentWrapper>
            </>
        )
    }
}
