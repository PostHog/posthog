import { useState } from 'react'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { WizardModeShell } from './WizardModeShell'

export function WizardCommandBlock({ hideHog = false }: { hideHog?: boolean } = {}): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const [castKey, setCastKey] = useState(0)

    // The `npx @posthog/wizard` CLI only targets cloud (US/EU) and dev instances —
    // self-hosted deployments have no preconfigured endpoint, so we hide the block
    // entirely rather than show a command that can't work. Matches SetupWizardBanner.
    if (!isCloudOrDev) {
        return <></>
    }

    return (
        <WizardModeShell hogCastKey={castKey} hideHog={hideHog} data-attr="wizard-command-block">
            <CommandBlock
                command={wizardCommand}
                copyLabel="Wizard command"
                ariaLabel="Copy wizard command"
                size="md"
                decoration="rainbow"
                className="bg-bg-light border border-border hover:border-primary"
                onCopy={(key) => setCastKey(key)}
            />
            <p className="text-xs text-muted mb-0">
                Auto-detects your framework, installs the SDK, and sets up event capture. Commit the changes and open a
                PR when you're ready.
            </p>
        </WizardModeShell>
    )
}
