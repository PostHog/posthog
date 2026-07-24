import { useActions, useValues } from 'kea'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { SlackIntegration } from 'scenes/integrations/components/SlackIntegration'
import MCPServerSettings from 'scenes/settings/environment/MCPServerSettings'
import { urls } from 'scenes/urls'

import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'

export function CompanionSetupModal(): JSX.Element {
    const { companionSetup } = useValues(quickstartLogic)
    const { closeCompanionSetup } = useActions(quickstartLogic)

    return (
        <LemonModal
            isOpen={companionSetup !== null}
            onClose={closeCompanionSetup}
            title={companionSetup === 'slack' ? 'Set up Slack' : 'Set up MCP'}
            width={640}
        >
            {companionSetup === 'slack' ? (
                <div className="flex flex-col gap-4">
                    <p className="mb-0">
                        Connect a Slack workspace to ask PostHog AI questions and send insights or alerts to channels.
                    </p>
                    <div className="rounded border bg-bg-light p-4">
                        <SlackIntegration next={urls.quickstart()} />
                    </div>
                    <Link
                        to={urls.integration('slack')}
                        onClick={() => captureQuickstartAction('open_slack_integration_settings')}
                    >
                        Open the full Slack integration settings
                    </Link>
                </div>
            ) : companionSetup === 'mcp' ? (
                <MCPServerSettings />
            ) : null}
        </LemonModal>
    )
}
