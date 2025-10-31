import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { DocumentationLink } from './DocumentationLink'
import { ManualCaptureNotice } from './ManualCaptureNotice'
import { ProxyNote } from './ProxyNote'

export function LLMLiteLLMInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>1. Install</h3>
            <CodeSnippet language={Language.Bash}>pip install litellm</CodeSnippet>

            <h3>2. Set Environment Variables</h3>
            <CodeSnippet language={Language.Bash}>{`export POSTHOG_API_KEY="${currentTeam?.api_token}"
export POSTHOG_API_URL="${apiHostOrigin()}"`}</CodeSnippet>

            <h3>3. Configure and Call</h3>
            <CodeSnippet language={Language.Python}>{`import litellm

# Enable PostHog callbacks
litellm.success_callback = ["posthog"]
litellm.failure_callback = ["posthog"]

# Call any LLM provider
response = litellm.completion(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Tell me a fun fact about hedgehogs"}],
    metadata={
        "user_id": "user_123"  # Maps to PostHog distinct_id
    }
)`}</CodeSnippet>

            <ProxyNote />

            <DocumentationLink provider="litellm" />

            <ManualCaptureNotice />
        </>
    )
}
