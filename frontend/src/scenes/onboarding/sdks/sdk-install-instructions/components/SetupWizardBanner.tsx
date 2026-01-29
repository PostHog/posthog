import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { Language } from 'lib/components/CodeSnippet'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

const SetupWizardBanner = ({
    integrationName,
    hide,
}: {
    integrationName: string
    hide?: boolean
}): JSX.Element | null => {
    const { preflight, isCloudOrDev } = useValues(preflightLogic)

    if (hide || !isCloudOrDev) {
        return null
    }

    const region = preflight?.region || Region.US
    const wizardCommand = `npx -y @posthog/wizard@latest${region === Region.EU ? ` --region eu` : ''}`

    return (
        <>
            <h2>Automated installation</h2>
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
            <LemonDivider label="OR" />
            <h2>Manual installation</h2>
        </>
    )
}

export default SetupWizardBanner
