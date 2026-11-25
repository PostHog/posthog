import posthog from 'posthog-js'
import { type ReactNode, useState } from 'react'

import { Text } from '@posthog/quill'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'

import { WizardModeShell } from './WizardModeShell'

export function WizardCommandBlock({
    subcommand,
    description,
}: {
    /** Wizard subcommand to run, e.g. `self-driving`. Omit for the plain SDK install. */
    subcommand?: string
    /** Replaces the default "what this does" line when the subcommand does something else. */
    description?: ReactNode
} = {}): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand(subcommand)
    const [castKey, setCastKey] = useState(0)
    const quillSurface = useQuillSurface()

    // The `npx @posthog/wizard` CLI only targets cloud (US/EU) and dev instances —
    // self-hosted deployments have no preconfigured endpoint, so we hide the block
    // entirely rather than show a command that can't work. Matches SetupWizardBanner.
    if (!isCloudOrDev) {
        return <></>
    }

    const descriptionText = description ?? (
        <>
            Auto-detects your framework, installs the SDK, and sets up event capture. Commit the changes and open a PR
            when you're ready.
        </>
    )

    const commandBlock = (
        <CommandBlock
            command={wizardCommand}
            copyLabel="Wizard command"
            ariaLabel="Copy wizard command"
            size="md"
            decoration="rainbow"
            className={
                quillSurface
                    ? 'bg-card border border-border hover:bg-fill-hover'
                    : 'bg-bg-light border border-border hover:border-primary'
            }
            onCopy={(key) => {
                setCastKey(key)
                posthog.capture('wizard command copy requested', {
                    event_source: 'wizard_ui',
                    command: subcommand ?? 'default',
                })
            }}
            // A subcommand pushes the displayed command past one line.
            condensed={!!subcommand}
        />
    )

    return (
        <WizardModeShell hogCastKey={castKey} data-attr="wizard-command-block">
            {quillSurface ? (
                // The quill token utilities on the command block only resolve inside a quill subtree.
                <div data-quill className="contents">
                    {commandBlock}
                </div>
            ) : (
                commandBlock
            )}
            {quillSurface ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {descriptionText}
                </Text>
            ) : (
                <p className="text-xs text-muted mb-0">{descriptionText}</p>
            )}
        </WizardModeShell>
    )
}
