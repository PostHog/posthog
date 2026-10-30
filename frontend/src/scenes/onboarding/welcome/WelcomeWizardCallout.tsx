import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'

import { useWizardCommand } from '../shared/useWizardCommand'
import { WizardHog } from '../shared/wizardHog'

export function WelcomeWizardCallout(): JSX.Element | null {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()

    // The wizard only targets cloud and dev instances.
    if (!isCloudOrDev) {
        return null
    }

    return (
        <div
            className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded border border-primary bg-surface-primary px-3 py-2"
            data-attr="onboarding-welcome-wizard"
        >
            <WizardHog className="size-10 shrink-0" />
            <div className="min-w-60 flex-1">
                <div className="font-semibold">Install PostHog with Wizard</div>
                <div className="text-xs text-secondary">
                    Run this in your app's folder to set up every product below. The setup agent adds the SDK and your
                    project token.
                </div>
            </div>
            <CommandBlock
                command={wizardCommand}
                copyLabel="Wizard command"
                ariaLabel="Copy wizard command"
                decoration="rainbow"
            />
        </div>
    )
}
