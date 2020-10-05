import React from 'react'
import './OnboardingWizard.scss'

import { VerificationPanel } from 'scenes/onboarding/panels/VerificationPanel'
import { AutocapturePanel } from 'scenes/onboarding/panels/AutocapturePanel'
import { InstructionsPanel } from 'scenes/onboarding/panels/InstructionsPanel'
import { MOBILE, WEB } from 'scenes/onboarding/constants'
import { useValues } from 'kea'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { FrameworkPanel } from 'scenes/onboarding/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/onboarding/panels/PlatformPanel'

export function OnboardingContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            {children}
        </div>
    )
}

export default function OnboardingWizard(): JSX.Element {
    const { platform, framework, customEvent, verify } = useValues(onboardingLogic)

    if (verify) {
        return (
            <OnboardingContainer>
                <VerificationPanel />
            </OnboardingContainer>
        )
    }

    if (framework) {
        return (
            <OnboardingContainer>
                <InstructionsPanel />
            </OnboardingContainer>
        )
    }

    if (!platform) {
        return (
            <OnboardingContainer>
                <PlatformPanel />
            </OnboardingContainer>
        )
    }

    if (platform === WEB && !customEvent) {
        return (
            <OnboardingContainer>
                <AutocapturePanel />
            </OnboardingContainer>
        )
    }

    if (platform === MOBILE || (platform === WEB && customEvent)) {
        return (
            <OnboardingContainer>
                <FrameworkPanel />
            </OnboardingContainer>
        )
    }

    return <></>
}
