import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { getSlackAppManifest, integrationsLogic } from './integrationsLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { IconDelete, IconSlack } from 'lib/components/icons'
import { Modal } from 'antd'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

export function SlackIntegration(): JSX.Element {
    const { slackIntegration, addToSlackButtonUrl } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)
    const [showSlackInstructions, setShowSlackInstructions] = useState(false)
    const { user } = useValues(userLogic)

    const onDeleteClick = (): void => {
        Modal.confirm({
            title: `Do you want to disconnect from Slack?`,
            content:
                'This cannot be undone. PostHog resources configured to use Slack will remain but will stop working.',
            okText: 'Yes, disconnect',
            okType: 'danger',
            onOk() {
                if (slackIntegration?.id) {
                    deleteIntegration(slackIntegration.id)
                }
            },
            cancelText: 'No thanks',
        })
    }

    return (
        <div>
            <p>
                Integrate with Slack directly to get more advanced options such as sending webhook events to{' '}
                <b>different channels</b> and <b>subscribing to an Insight or Dashboard</b> for regular reports to Slack
                channels of your choice. Guidance on integrating with Slack available{' '}
                <a href="https://posthog.com/docs/integrate/third-party/slack">in our docs</a>.
            </p>

            <p>
                {slackIntegration ? (
                    <div className="rounded border-all flex justify-between items-center pa-05">
                        <div className="flex items-center gap ml-05">
                            <IconSlack />
                            <div>
                                <div>
                                    Connected to <strong>{slackIntegration.config.team.name}</strong> workspace
                                </div>
                                {slackIntegration.created_by ? (
                                    <UserActivityIndicator
                                        at={slackIntegration.created_at}
                                        by={slackIntegration.created_by}
                                        prefix={'Updated'}
                                        className={'text-muted'}
                                    />
                                ) : null}
                            </div>
                        </div>

                        <LemonButton type="secondary" status="danger" onClick={onDeleteClick} icon={<IconDelete />}>
                            Disconnect
                        </LemonButton>
                    </div>
                ) : addToSlackButtonUrl() ? (
                    <a href={addToSlackButtonUrl() || ''}>
                        <img
                            alt="Add to Slack"
                            height="40"
                            width="139"
                            src="https://platform.slack-edge.com/img/add_to_slack.png"
                            srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                        />
                    </a>
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
                                        <a href="https://api.slack.com/apps" target="_blank">
                                            Slack Apps
                                        </a>
                                    </li>
                                    <li>Create an App using the provided template</li>
                                    <li>
                                        <Link to={urls.instanceSettings()}>Go to Instance Settings</Link> and update the{' '}
                                        <code>"SLACK_"</code> properties using the values from the{' '}
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
            </p>
        </div>
    )
}
