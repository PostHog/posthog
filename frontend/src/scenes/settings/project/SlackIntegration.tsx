import { IconTrash } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { getSlackAppManifest, integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackIntegrationView } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

export function SlackIntegration(): JSX.Element {
    const { slackIntegrations, addToSlackButtonUrl } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)
    const [showSlackInstructions, setShowSlackInstructions] = useState(false)
    const { user } = useValues(userLogic)

    const onDeleteClick = (id: number): void => {
        LemonDialog.open({
            title: `Do you want to disconnect from Slack?`,
            description:
                'This cannot be undone. PostHog resources configured to use this Slack workspace will remain but will stop working.',
            primaryButton: {
                children: 'Yes, disconnect',
                status: 'danger',
                onClick: () => {
                    if (id) {
                        deleteIntegration(id)
                    }
                },
            },
            secondaryButton: {
                children: 'No thanks',
            },
        })
    }

    return (
        <div>
            <p>
                Integrate with Slack directly to get more advanced options such as{' '}
                <b>subscribing to an Insight or Dashboard</b> for regular reports to Slack channels of your choice.
                Guidance on integrating with Slack available{' '}
                <Link to="https://posthog.com/docs/product-analytics/subscriptions#slack-subscriptions">
                    in our docs
                </Link>
                .
            </p>

            <div className="space-y-2">
                {slackIntegrations?.map((integration) => (
                    <SlackIntegrationView
                        key={integration.id}
                        integration={integration}
                        suffix={
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => onDeleteClick(integration.id)}
                                icon={<IconTrash />}
                            >
                                Disconnect
                            </LemonButton>
                        }
                    />
                ))}

                <div>
                    {addToSlackButtonUrl() ? (
                        <Link to={addToSlackButtonUrl() || ''}>
                            <img
                                alt="Connect to Slack workspace"
                                height="40"
                                width="139"
                                src="https://platform.slack-edge.com/img/add_to_slack.png"
                                srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                            />
                        </Link>
                    ) : user?.is_staff ? (
                        !showSlackInstructions ? (
                            <>
                                <LemonButton type="secondary" onClick={() => setShowSlackInstructions(true)}>
                                    Show Instructions
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <h5>To get started</h5>
                                <p>
                                    <ol>
                                        <li>Copy the below Slack App Template</li>
                                        <li>
                                            Go to{' '}
                                            <Link to="https://api.slack.com/apps" target="_blank">
                                                Slack Apps
                                            </Link>
                                        </li>
                                        <li>Create an App using the provided template</li>
                                        <li>
                                            <Link to={urls.instanceSettings()}>Go to Instance Settings</Link> and update
                                            the <code>"SLACK_"</code> properties using the values from the{' '}
                                            <b>App Credentials</b> section of your Slack Apps
                                        </li>
                                    </ol>

                                    <CodeSnippet language={Language.JSON}>
                                        {JSON.stringify(getSlackAppManifest(), null, 2)}
                                    </CodeSnippet>
                                </p>
                            </>
                        )
                    ) : (
                        <p className="text-muted">
                            This PostHog instance is not configured for Slack. Please contact the instance owner to
                            configure it.
                        </p>
                    )}
                </div>
            </div>
        </div>
    )
}
