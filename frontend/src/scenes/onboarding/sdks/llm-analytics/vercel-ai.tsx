import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { DocumentationLink } from './DocumentationLink'
import { ManualCaptureNotice } from './ManualCaptureNotice'
import { ProxyNote } from './ProxyNote'

export function LLMVercelAIInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>1. Install</h3>
            <CodeSnippet language={Language.Bash}>npm install @posthog/ai posthog-node ai @ai-sdk/openai</CodeSnippet>

            <h3>2. Initialize</h3>
            <CodeSnippet language={Language.JavaScript}>{`import { PostHog } from "posthog-node"
import { withTracing } from "@posthog/ai"
import { generateText } from "ai"
import { createOpenAI } from "@ai-sdk/openai"

const phClient = new PostHog('${currentTeam?.api_token}', {
    host: '${apiHostOrigin()}'
})

const openaiClient = createOpenAI({
    apiKey: 'your_openai_api_key',
    compatibility: 'strict'
})`}</CodeSnippet>

            <h3>3. Wrap and Call</h3>
            <CodeSnippet
                language={Language.JavaScript}
            >{`const model = withTracing(openaiClient("gpt-4o-mini"), phClient, {
    posthogDistinctId: "user_123"
})

const { text } = await generateText({
    model: model,
    prompt: "Tell me a fun fact about hedgehogs"
})

phClient.shutdown()`}</CodeSnippet>

            <ProxyNote />

            <DocumentationLink provider="vercel-ai" />

            <ManualCaptureNotice />
        </>
    )
}
