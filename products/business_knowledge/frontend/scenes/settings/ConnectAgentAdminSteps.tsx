import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AgentConfigSnippet } from './AgentConfigSnippet'
import { ConnectAgentKeyForm } from './ConnectAgentKeyForm'
import { ConnectAgentKeysTable } from './ConnectAgentKeysTable'
import { connectAgentLogic } from './connectAgentLogic'
import { QuillAgentConfigSnippet } from './QuillAgentConfigSnippet'

export function ConnectAgentAdminSteps(): JSX.Element {
    const { createdKey } = useValues(connectAgentLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const configStep = createdKey?.value
        ? 'Add the PostHog MCP server to your agent. This configuration holds your new key:'
        : 'Add the PostHog MCP server to your agent, and replace the placeholder with the key. Most agents accept this format:'

    if (todayRailNav) {
        return (
            <>
                <ol className="m-0 pl-5 flex flex-col gap-2 list-decimal">
                    <Text size="xs" render={<li />}>
                        <div className="flex flex-col gap-2">
                            <span>Create a key for the library the agent can read.</span>
                            <ConnectAgentKeyForm />
                            <Text size="xs" variant="muted" render={<span />}>
                                To let an agent read every library,{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.settings('environment-secret-api-keys')} />}
                                    // pinned: data-attr value. Autocapture insights and tests select on it.
                                    data-attr="business-knowledge-connect-agent-create-key"
                                >
                                    create a project secret API key
                                </Button>{' '}
                                with the <code>business_knowledge:read</code> scope.
                            </Text>
                        </div>
                    </Text>
                    <Text size="xs" render={<li />}>
                        {configStep}
                    </Text>
                </ol>
                {createdKey?.value && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {`Copy the configuration now. PostHog does not show the key "${createdKey.label}" again.`}
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                <QuillAgentConfigSnippet apiKey={createdKey?.value ?? undefined} />
                <ConnectAgentKeysTable />
            </>
        )
    }

    return (
        <>
            <ol className="m-0 pl-5 flex flex-col gap-2 list-decimal">
                <li>
                    <div className="flex flex-col gap-2">
                        <span>Create a key for the library the agent can read.</span>
                        <ConnectAgentKeyForm />
                        <span className="text-xs text-secondary">
                            To let an agent read every library,{' '}
                            <Link
                                to={urls.settings('environment-secret-api-keys')}
                                // pinned: data-attr value. Autocapture insights and tests select on it.
                                data-attr="business-knowledge-connect-agent-create-key"
                            >
                                create a project secret API key
                            </Link>{' '}
                            with the <code>business_knowledge:read</code> scope.
                        </span>
                    </div>
                </li>
                <li>{configStep}</li>
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
