import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'
import { teamLogic } from 'scenes/teamLogic'

import { SDKKey } from '~/types'

import {
    buildSDKSelectOptions,
    filterRequiredSteps,
    filterToFirstRequiredStep,
    SDK_CONFIGS,
} from './SDKSetupInstructions'

const PROXY_SDK_OPTIONS = buildSDKSelectOptions(['web', 'mobile'])

export function ProxySDKSetup(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const [selectedSDK, setSelectedSDK] = useState<SDKKey>(SDKKey.JS_WEB)
    const [showFullSetup, setShowFullSetup] = useState(false)

    const config = useMemo(() => SDK_CONFIGS[selectedSDK], [selectedSDK])

    if (currentTeamLoading && !currentTeam) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-1/2 h-4" />
                <LemonSkeleton repeat={3} />
            </div>
        )
    }

    if (!config) {
        return <></>
    }

    const { Installation, snippets, wizardIntegrationName, docsLink, name } = config

    return (
        <div className="space-y-4 max-w-200">
            <LemonSelect
                value={selectedSDK}
                onChange={(value) => {
                    setSelectedSDK(value)
                    setShowFullSetup(false)
                }}
                options={PROXY_SDK_OPTIONS}
                className="max-w-80"
            />
            <OnboardingDocsContentWrapper snippets={snippets} minimal useReverseProxy>
                <Installation modifySteps={filterToFirstRequiredStep} />
            </OnboardingDocsContentWrapper>
            <div className="flex items-center gap-2">
                <LemonButton type="secondary" size="small" onClick={() => setShowFullSetup(true)}>
                    View full setup instructions
                </LemonButton>
                <Link to={docsLink} target="_blank" className="text-sm">
                    {name} docs
                </Link>
            </div>
            <LemonModal
                isOpen={showFullSetup}
                onClose={() => setShowFullSetup(false)}
                title={`${name} setup`}
                width={640}
            >
                {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                <OnboardingDocsContentWrapper snippets={snippets} useReverseProxy>
                    <Installation modifySteps={filterRequiredSteps} />
                </OnboardingDocsContentWrapper>
                <div className="mt-4">
                    <Link to={docsLink} target="_blank">
                        View full {name} documentation
                    </Link>
                </div>
            </LemonModal>
        </div>
    )
}
