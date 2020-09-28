import React from 'react'
import './OnboardingWizard.scss'

import { VerificationPanel } from 'scenes/onboarding/panels/VerificationPanel'
import { AutocapturePanel } from 'scenes/onboarding/panels/AutocapturePanel'
import { InstructionsPanel } from 'scenes/onboarding/panels/InstructionsPanel'
import { MOBILE, WEB } from 'scenes/onboarding/constants'
import { useValues } from 'kea'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { FrameworkPanel } from 'scenes/onboarding/panels/FrameworkPanel'
import { PlatformTypePanel } from 'scenes/onboarding/panels/PlatformTypePanel'

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
    const { platformType, framework, customEvent, verify } = useValues(onboardingLogic)

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

    if (!platformType) {
        return (
            <OnboardingContainer>
                <PlatformTypePanel />
            </OnboardingContainer>
        )
    }

    if (platformType === WEB && !customEvent) {
        return (
            <OnboardingContainer>
                <AutocapturePanel />
            </OnboardingContainer>
        )
    }

    if (platformType === MOBILE || (platformType === WEB && customEvent)) {
        return (
            <OnboardingContainer>
                <FrameworkPanel />
            </OnboardingContainer>
        )
    }

    return <></>
}
