import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { AgentConfigSnippet } from './AgentConfigSnippet'
import { ConnectAgentKeyForm } from './ConnectAgentKeyForm'
import { ConnectAgentKeysTable } from './ConnectAgentKeysTable'
import { connectAgentLogic } from './connectAgentLogic'

export function ConnectAgentAdminSteps(): JSX.Element {
    const { createdKey } = useValues(connectAgentLogic)

    return (
        <>
            <ol className="m-0 pl-5 flex flex-col gap-2 list-decimal">
                <li>
                    <div className="flex flex-col gap-2">
                        <span>Create a key, and choose what the agent can read.</span>
                        <ConnectAgentKeyForm />
                    </div>
                </li>
                <li>
                    {createdKey?.value
                        ? 'Add the PostHog MCP server to your agent. This configuration holds your new key:'
                        : 'Add the PostHog MCP server to your agent, and replace the placeholder with the key. Most agents accept this format:'}
                </li>
            </ol>
            {createdKey?.value && (
                <LemonBanner type="info">
                    Copy the configuration now. PostHog does not show the key "{createdKey.label}" again.
                </LemonBanner>
            )}
            <AgentConfigSnippet apiKey={createdKey?.value ?? undefined} />
            <ConnectAgentKeysTable />
        </>
    )
}
