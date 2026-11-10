import { useRef } from 'react'

import { IconCopy } from '@posthog/icons'
import { Button, anchoredToast } from '@posthog/quill'

import { writeToClipboard } from 'lib/utils/writeToClipboard'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'

export function TodayWizardCommand({ onCopy }: { onCopy: () => void }): JSX.Element | null {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const buttonRef = useRef<HTMLButtonElement>(null)

    if (!isCloudOrDev) {
        return null
    }

    const copy = async (): Promise<void> => {
        const outcome = await writeToClipboard(wizardCommand)
        if (buttonRef.current) {
            anchoredToast({
                description: outcome === 'copied' ? 'Copied' : 'Could not copy. Select the command and copy it.',
                anchor: buttonRef.current,
                side: 'top',
            })
        }
        if (outcome === 'copied') {
            onCopy()
        }
    }

    return (
        <div className="TodayWizardCommand">
            <code translate="no" className="TodayWizardCommand__code">
                {wizardCommand}
            </code>
            <Button
                ref={buttonRef}
                variant="link-muted"
                size="icon-sm"
                aria-label="Copy the Wizard command"
                onClick={() => void copy()}
                data-attr="today-get-started-wizard-copy"
            >
                <IconCopy />
            </Button>
        </div>
    )
}
