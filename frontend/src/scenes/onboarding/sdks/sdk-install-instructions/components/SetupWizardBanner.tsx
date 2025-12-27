import { Language } from 'lib/components/CodeSnippet'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

const SetupWizardBanner = ({ integrationName }: { integrationName: string }): JSX.Element => {
    const wizardCommand = 'npx -y @posthog/wizard@latest'

    return (
        <LemonBanner type="info" hideIcon={true}>
            <h3 className="flex items-center gap-2 pb-1">
                <LemonTag type="warning">BETA</LemonTag> AI setup wizard
            </h3>
            <div className="flex flex-col p-2">
                <p className="font-normal pb-1">Try using the AI setup wizard to automatically install PostHog.</p>
                <p className="font-normal pb-2">
                    Run the following command from the root of your {integrationName} project.
                </p>
                <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
            </div>
        </LemonBanner>
    )
}

export default SetupWizardBanner
