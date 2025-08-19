import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

import { SDKInstallNodeInstructions } from '../sdk-install-instructions'
import { NodeManualCapture } from './FinalSteps'

export function NodeInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <SDKInstallNodeInstructions enableExceptionAutocapture />
            <p>
                If you are using the Express framework you will need to call <code>setupExpressErrorHandler</code> with
                your PostHog client and Express app. This is because Express handles uncaught errors internally meaning
                exception autocapture will not work by default.
            </p>
            <CodeSnippet language={Language.TypeScript}>
                {expressHandler(currentTeam?.api_token ?? '<API_TOKEN>')}
            </CodeSnippet>
            <NodeManualCapture />
        </>
    )
}

const expressHandler = (api_token: string): string => `// server.ts

import express from 'express'
import { PostHog, setupExpressErrorHandler } from 'posthog-node'

const app = express()
const posthog = new PostHog('${api_token}')

setupExpressErrorHandler(posthog, app)
`
