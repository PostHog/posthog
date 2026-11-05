import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useWizardCommand } from 'lib/onboarding/useWizardCommand'
import { WizardCommandBlock } from 'lib/onboarding/wizard-command/WizardCommandBlock'

import { SDKSetupInstructions } from './SDKSetupInstructions'

export function SDKInstallOptions(): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const [showManualSetup, setShowManualSetup] = useState(false)

    // The wizard CLI only reaches cloud and dev instances, so self-hosted keeps the manual instructions as the only path.
    if (!isCloudOrDev) {
        return <SDKSetupInstructions />
    }

    return (
        <div className="space-y-4 max-w-200">
            <p className="mb-0">Run this command from the root of your project to start the setup agent.</p>
            <WizardCommandBlock />
            <div>
                <LemonButton
                    icon={showManualSetup ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => setShowManualSetup(!showManualSetup)}
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
