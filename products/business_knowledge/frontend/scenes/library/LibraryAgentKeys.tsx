import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { AgentConfigSnippet } from '../settings/AgentConfigSnippet'
import { ConnectAgentKeyForm } from '../settings/ConnectAgentKeyForm'
import { ConnectAgentKeysTable } from '../settings/ConnectAgentKeysTable'
import { connectAgentLogic } from '../settings/connectAgentLogic'

export function LibraryAgentKeys(): JSX.Element {
    const { createdKey } = useValues(connectAgentLogic)

    return (
        <>
            <ConnectAgentKeyForm />
            {createdKey?.value && (
                <>
                    <LemonBanner type="info">
                        Add this configuration to your agent, and copy it now. PostHog does not show the key "
                        {createdKey.label}" again.
                    </LemonBanner>
                    <AgentConfigSnippet apiKey={createdKey.value} />
                </>
            )}
            <ConnectAgentKeysTable />
        </>
    )
}
