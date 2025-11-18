import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { DocumentationLink } from './DocumentationLink'
import { LanguageSelector, useLanguageSelector } from './LanguageSelector'
import { ManualCaptureNotice } from './ManualCaptureNotice'
import { ProxyNote } from './ProxyNote'

export function LLMLangChainInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [language, setLanguage] = useLanguageSelector('node')

    return (
        <>
            <LanguageSelector language={language} onChange={setLanguage} />

            {language === 'node' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>
                        npm install @posthog/ai posthog-node @langchain/openai @langchain/core
                    </CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.JavaScript}>{`import { PostHog } from 'posthog-node'
import { LangChainCallbackHandler } from '@posthog/ai'
import { ChatOpenAI } from '@langchain/openai'

const phClient = new PostHog('${currentTeam?.api_token}', {
    host: '${apiHostOrigin()}'
})

const callbackHandler = new LangChainCallbackHandler({
    client: phClient,
    distinctId: 'user_123'
})`}</CodeSnippet>

                    <h3>3. Use with LangChain</h3>
                    <CodeSnippet language={Language.JavaScript}>{`const model = new ChatOpenAI({
    apiKey: "your_openai_api_key",
    model: "gpt-4o-mini"
})

const response = await model.invoke(
    "Tell me a fun fact about hedgehogs",
    { callbacks: [callbackHandler] }
)

phClient.shutdown()`}</CodeSnippet>

                    <ProxyNote />

                    <DocumentationLink provider="langchain" />
                </>
            )}

            {language === 'python' && (
                <>
                    <h3>1. Install</h3>
                    <CodeSnippet language={Language.Bash}>pip install posthog langchain langchain-openai</CodeSnippet>

                    <h3>2. Initialize</h3>
                    <CodeSnippet language={Language.Python}>{`from posthog.ai.langchain import CallbackHandler
from langchain_openai import ChatOpenAI
from posthog import Posthog

posthog = Posthog("${currentTeam?.api_token}", host="${apiHostOrigin()}")

callback_handler = CallbackHandler(
    client=posthog,
    distinct_id="user_123"
)`}</CodeSnippet>

                    <h3>3. Use with LangChain</h3>
                    <CodeSnippet language={Language.Python}>{`model = ChatOpenAI(
    openai_api_key="your_openai_api_key",
    model="gpt-4o-mini"
)

response = model.invoke(
    "Tell me a fun fact about hedgehogs",
    config={"callbacks": [callback_handler]}
)`}</CodeSnippet>

                    <ProxyNote />

                    <DocumentationLink provider="langchain" />
                </>
            )}

            <ManualCaptureNotice />
        </>
    )
}
