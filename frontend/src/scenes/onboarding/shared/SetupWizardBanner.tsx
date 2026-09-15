import type { ReactNode } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { Language } from 'lib/components/CodeSnippet'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { useWizardCommand } from './useWizardCommand'

const SetupWizardBanner = ({
    integrationName,
    hide,
    subcommand,
    description,
}: {
    integrationName: string
    hide?: boolean
    /** Wizard subcommand to run, e.g. `error-tracking`. Omit for the plain SDK install. */
    subcommand?: string
    /** Replaces the default "what this does" line when the subcommand does something else. */
    description?: ReactNode
}): JSX.Element | null => {
    const { wizardCommand, isCloudOrDev } = useWizardCommand(subcommand)

    if (hide || !isCloudOrDev) {
        return null
    }

    return (
        <>
            <h2>Automated installation</h2>
            <LemonBanner type="info" hideIcon={true}>
                <h3 className="pb-1">AI setup wizard</h3>
                <div className="flex flex-col p-2">
                    <p className="font-normal pb-1">
                        {description ?? 'Try using the AI setup wizard to automatically install PostHog.'}
                    </p>
                    <p className="font-normal pb-2">
                        Run the following command from the root of your {integrationName} project.
                    </p>
                    <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
                </div>
            </LemonBanner>
            <LemonDivider label="OR" />
            <h2>Manual installation</h2>
        </>
    )
}

export default SetupWizardBanner
