import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { DocumentationLink } from './DocumentationLink'
import { LanguageSelector, useLanguageSelector } from './LanguageSelector'
import { ManualCaptureNotice } from './ManualCaptureNotice'
import { ProxyNote } from './ProxyNote'

export function LLMGoogleInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [language, setLanguage] = useLanguageSelector('node')

    return (
        <>
            <LanguageSelector language={language} onChange={setLanguage} />

            {language === 'node' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>
                        npm install @posthog/ai posthog-node @google/generative-ai
                    </CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.JavaScript}>{`import { GoogleGenerativeAI } from '@posthog/ai'
import { PostHog } from 'posthog-node'

const phClient = new PostHog('${currentTeam?.api_token}', {
    host: '${apiHostOrigin()}'
})

const client = new GoogleGenerativeAI({
    apiKey: 'your_google_api_key',
    posthog: phClient
})`}</CodeSnippet>

                    <h3>3. Call Google Gemini</h3>
                    <CodeSnippet
                        language={Language.JavaScript}
                    >{`const model = client.getGenerativeModel({ model: "gemini-2.0-flash-exp" })

const response = await model.generateContent({
    contents: [{ role: "user", parts: [{ text: "Tell me a fun fact about hedgehogs" }] }],
    posthogDistinctId: "user_123"
})

phClient.shutdown()`}</CodeSnippet>

                    <ProxyNote />

                    <DocumentationLink provider="google" />
                </>
            )}

            {language === 'python' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>pip install posthog google-generativeai</CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.Python}>{`from posthog.ai.gemini import Client
from posthog import Posthog

posthog = Posthog("${currentTeam?.api_token}", host="${apiHostOrigin()}")

client = Client(
    api_key="your_google_api_key",
    posthog_client=posthog
)`}</CodeSnippet>

                    <h3>3. Call Google Gemini</h3>
                    <CodeSnippet language={Language.Python}>{`model = client.GenerativeModel("gemini-2.0-flash-exp")

response = model.generate_content(
    contents="Tell me a fun fact about hedgehogs",
    posthog_distinct_id="user_123"
)`}</CodeSnippet>

                    <ProxyNote />

                    <DocumentationLink provider="google" />
                </>
            )}

            <ManualCaptureNotice />
        </>
    )
}
