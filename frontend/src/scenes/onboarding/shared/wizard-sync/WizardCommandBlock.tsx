import { type ReactNode, useState } from 'react'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'

import { WizardModeShell } from './WizardModeShell'

export function WizardCommandBlock({
    hideHog = false,
    subcommand,
    description,
}: {
    hideHog?: boolean
    /** Wizard subcommand to run, e.g. `self-driving`. Omit for the plain SDK install. */
    subcommand?: string
    /** Replaces the default "what this does" line when the subcommand does something else. */
    description?: ReactNode
} = {}): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand(subcommand)
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
                // A subcommand pushes the displayed command past one line.
                condensed={!!subcommand}
            />
            <p className="text-xs text-muted mb-0">
                {description ?? (
                    <>
                        Auto-detects your framework, installs the SDK, and sets up event capture. Commit the changes and
                        open a PR when you're ready.
                    </>
                )}
            </p>
        </WizardModeShell>
    )
}
