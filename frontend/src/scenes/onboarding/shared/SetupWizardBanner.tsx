import { LemonDivider } from '@posthog/lemon-ui'

import { Language } from 'lib/components/CodeSnippet'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { useWizardCommand } from './useWizardCommand'
import { WizardFrameworkBadges } from './wizard-sync/WizardModeShell'

const SetupWizardBanner = ({
    integrationName,
    hide,
}: {
    integrationName: string
    hide?: boolean
}): JSX.Element | null => {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()

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
                        The setup wizard detects your framework, installs the SDK, and sets up event capture.
                    </p>
                    <p className="font-normal pb-1">
                        It is a Node command-line tool that you run with npx. It supports many frameworks and languages,
                        not only JavaScript ones.
                    </p>
                    <p className="font-normal pb-2">
                        Run this command from the root of your {integrationName} project.
                    </p>
                    <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
                    <div className="pt-3">
                        <WizardFrameworkBadges />
                    </div>
                </div>
            </LemonBanner>
            <LemonDivider label="OR" />
            <h2>Manual installation</h2>
        </>
    )
}

export default SetupWizardBanner
