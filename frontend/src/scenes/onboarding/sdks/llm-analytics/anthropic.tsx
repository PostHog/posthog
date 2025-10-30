import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { DocumentationLink } from './DocumentationLink'
import { LanguageSelector, useLanguageSelector } from './LanguageSelector'
import { ManualCaptureNotice } from './ManualCaptureNotice'

export function LLMAnthropicInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [language, setLanguage] = useLanguageSelector('node')

    return (
        <>
            <LanguageSelector language={language} onChange={setLanguage} />

            {language === 'node' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>
                        npm install @posthog/ai posthog-node @anthropic-ai/sdk
                    </CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.JavaScript}>{`import { Anthropic } from '@posthog/ai'
import { PostHog } from 'posthog-node'

const phClient = new PostHog('${currentTeam?.api_token}', {
    host: '${apiHostOrigin()}'
})

const client = new Anthropic({
    apiKey: 'your_anthropic_api_key',
    posthog: phClient
})`}</CodeSnippet>

                    <h3>3. Call Anthropic</h3>
                    <CodeSnippet language={Language.JavaScript}>{`const response = await client.messages.create({
    model: "claude-3-5-sonnet-latest",
    max_tokens: 1024,
    messages: [{ role: "user", content: "Tell me a fun fact about hedgehogs" }],
    posthogDistinctId: "user_123"
})

phClient.shutdown()`}</CodeSnippet>

                    <DocumentationLink provider="anthropic" />
                </>
            )}

            {language === 'python' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>pip install posthog anthropic</CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.Python}>{`from posthog.ai.anthropic import Anthropic
from posthog import Posthog

posthog = Posthog("${currentTeam?.api_token}", host="${apiHostOrigin()}")

client = Anthropic(
    api_key="your_anthropic_api_key",
    posthog_client=posthog
)`}</CodeSnippet>

                    <h3>3. Call Anthropic</h3>
                    <CodeSnippet language={Language.Python}>{`response = client.messages.create(
    model="claude-3-5-sonnet-latest",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Tell me a fun fact about hedgehogs"}],
    posthog_distinct_id="user_123"
)`}</CodeSnippet>

                    <DocumentationLink provider="anthropic" />
                </>
            )}

            <ManualCaptureNotice />
        </>
    )
}
