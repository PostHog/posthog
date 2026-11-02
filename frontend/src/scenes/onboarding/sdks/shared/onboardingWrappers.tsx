import React from 'react'

import { StepDefinition } from '@posthog/shared-onboarding/steps'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/shared/SetupWizardBanner'

import { SDKKey } from '~/types'

import { AdvertiseMobileReplay, type AdvertiseMobileReplayContext } from '../session-replay/AdvertiseMobileReplay'

interface OnboardingDocsWrapperOptions {
    Installation: React.ComponentType<any>
    snippets?: Record<string, React.ComponentType<any>>
    wizardIntegrationName?: string
    modifySteps?: (steps: StepDefinition[]) => StepDefinition[]
}

/**
 * Helper to create wrapped instruction components without recreating snippets on every render.
 * Used by product-analytics, feature-flags, experiments, and llm-analytics onboarding flows.
 */
export function withOnboardingDocsWrapper(options: OnboardingDocsWrapperOptions): () => JSX.Element {
    const { Installation, snippets, wizardIntegrationName, modifySteps } = options
    return function WrappedInstallation() {
        return (
            <>
                {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                <OnboardingDocsContentWrapper snippets={snippets}>
                    <Installation modifySteps={modifySteps} />
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
