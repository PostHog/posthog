import React from 'react'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

import SetupWizardBanner from '../sdk-install-instructions/components/SetupWizardBanner'
import { AdvertiseMobileReplay, AdvertiseMobileReplayContext } from '../session-replay/SessionReplaySDKInstructions'

interface OnboardingDocsWrapperOptions {
    Installation: React.ComponentType<any>
    snippets?: Record<string, React.ComponentType<any>>
    wizardIntegrationName?: string
}

/**
 * Helper to create wrapped instruction components without recreating snippets on every render.
 * Used by product-analytics, feature-flags, experiments, and llm-analytics onboarding flows.
 */
export function withOnboardingDocsWrapper(options: OnboardingDocsWrapperOptions): () => JSX.Element {
    const { Installation, snippets, wizardIntegrationName } = options
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

interface MobileReplayOptions {
    Installation: React.ComponentType<any>
    sdkKey: SDKKey
    onboardingContext: AdvertiseMobileReplayContext
    snippets?: Record<string, React.ComponentType<any>>
    wizardIntegrationName?: string
}

/**
 * Helper to create components with Installation + AdvertiseMobileReplay (for mobile SDKs).
 * Used for Android, iOS, React Native, and Flutter SDKs.
 */
export function withMobileReplay(options: MobileReplayOptions): () => JSX.Element {
    const { Installation, sdkKey, onboardingContext, snippets, wizardIntegrationName } = options
    return function WrappedInstallation() {
        return (
            <>
                {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                <OnboardingDocsContentWrapper snippets={snippets}>
                    <Installation />
                    <AdvertiseMobileReplay context={onboardingContext} sdkKey={sdkKey} />
                </OnboardingDocsContentWrapper>
            </>
        )
    }
}
