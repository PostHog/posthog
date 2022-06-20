import React, { useState } from 'react'
import { useValues } from 'kea'
import { getSlackAppManifest, integrationsLogic } from './integrationsLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { LemonButton } from '@posthog/lemon-ui'
import { IconDelete, IconSlack } from 'lib/components/icons'

export function SlackIntegration(): JSX.Element {
    const { slackIntegration, addToSlackButtonUrl } = useValues(integrationsLogic)
    const [showSlackInstructions, setShowSlackInstructions] = useState(false)

    const onClick = () => {
        console.log('YO!')
    }

    return (
        <div>
            <p>
                Integrate with Slack directly to get more advanced options such as sending webhook events to{' '}
                <b>different channels</b> and <b>subscribing to an Insight or Dashboard</b> for regular reports to Slack
                channels of your choice
                <br />
                Guidance on integrating with Slack available{' '}
                <a href="https://posthog.com/docs/integrations/slack">in our docs</a>.
            </p>

            <p>
                {slackIntegration ? (
                    <div className="border-all space-between-items items-center pa-05">
                        <div className="flex items-center gap-05 pl">
                            <IconSlack />
                            <span>
                                Connected to <strong>{slackIntegration.config.team.name}</strong> workspace
                            </span>
                        </div>

                        <LemonButton type="secondary" status="danger" onClick={onClick} icon={<IconDelete />}>
                            Disconnect
                        </LemonButton>
                    </div>
                ) : addToSlackButtonUrl ? (
                    <a href={addToSlackButtonUrl}>
                        <img
                            alt="Add to Slack"
                            height="40"
                            width="139"
                            src="https://platform.slack-edge.com/img/add_to_slack.png"
                            srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                        />
                    </a>
                ) : !showSlackInstructions ? (
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
                                <li>Return here and enter the values from the created Slack App</li>
                            </ol>

                            <CodeSnippet language={Language.JSON}>
                                {JSON.stringify(getSlackAppManifest(), null, 2)}
                            </CodeSnippet>
                        </p>
                    </>
                )}
            </p>
        </div>
    )
}
