import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { DocumentationLink } from './DocumentationLink'
import { LanguageSelector, useLanguageSelector } from './LanguageSelector'
import { ManualCaptureNotice } from './ManualCaptureNotice'
import { ProxyNote } from './ProxyNote'

export function LLMOpenRouterInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [language, setLanguage] = useLanguageSelector('node')

    return (
        <>
            <LanguageSelector language={language} onChange={setLanguage} />

            {language === 'node' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>npm install @posthog/ai posthog-node openai</CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.JavaScript}>{`import { OpenAI } from '@posthog/ai'
import { PostHog } from 'posthog-node'

const phClient = new PostHog('${currentTeam?.api_token}', {
    host: '${apiHostOrigin()}'
})

const openai = new OpenAI({
    baseURL: 'https://openrouter.ai/api/v1',
    apiKey: 'your_openrouter_api_key',
    posthog: phClient
})`}</CodeSnippet>

                    <h3>3. Call OpenRouter</h3>
                    <CodeSnippet
                        language={Language.JavaScript}
                    >{`const completion = await openai.chat.completions.create({
    model: "anthropic/claude-3.5-sonnet",
    messages: [{ role: "user", content: "Tell me a fun fact about hedgehogs" }],
    posthogDistinctId: "user_123"
})

phClient.shutdown()`}</CodeSnippet>

                    <ProxyNote />

                    <DocumentationLink provider="openrouter" />
                </>
            )}

            {language === 'python' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>pip install posthog openai</CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.Python}>{`from posthog.ai.openai import OpenAI
from posthog import Posthog

posthog = Posthog("${currentTeam?.api_token}", host="${apiHostOrigin()}")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="your_openrouter_api_key",
    posthog_client=posthog
)`}</CodeSnippet>

                    <h3>3. Call OpenRouter</h3>
                    <CodeSnippet language={Language.Python}>{`response = client.chat.completions.create(
    model="anthropic/claude-3.5-sonnet",
    messages=[{"role": "user", "content": "Tell me a fun fact about hedgehogs"}],
    posthog_distinct_id="user_123"
)`}</CodeSnippet>

                    <ProxyNote />

                    <DocumentationLink provider="openrouter" />
                </>
            )}

            <ManualCaptureNotice />
        </>
    )
}
