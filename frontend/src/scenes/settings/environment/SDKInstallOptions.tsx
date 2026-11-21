import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-command/WizardCommandBlock'

import { QuillSDKInstallOptions } from './QuillSDKInstallOptions'
import { SDKSetupInstructions } from './SDKSetupInstructions'

export function SDKInstallOptions(): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const [showManualSetup, setShowManualSetup] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // The wizard CLI only reaches cloud and dev instances, so self-hosted keeps the manual instructions as the only path.
    if (!isCloudOrDev) {
        return <SDKSetupInstructions />
    }

    const toggleManualSetup = (): void => setShowManualSetup(!showManualSetup)

    if (todayRailNav) {
        return <QuillSDKInstallOptions showManualSetup={showManualSetup} onShowManualSetupChange={setShowManualSetup} />
    }

    return (
        <div className="space-y-4 max-w-200">
            <p className="mb-0">Run this command from the root of your project to start the setup agent.</p>
            <WizardCommandBlock />
            <div>
                <LemonButton
                    icon={showManualSetup ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={toggleManualSetup}
                    size="small"
                    type="tertiary"
                    data-attr="sdk-setup-manual-toggle"
                >
                    Set up manually
                </LemonButton>
                {showManualSetup && (
                    <div className="mt-3">
                        <SDKSetupInstructions />
                    </div>
                )}
            </div>
        </div>
    )
}
