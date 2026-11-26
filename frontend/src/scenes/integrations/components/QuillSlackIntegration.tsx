import { Button, Heading, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

export function QuillSlackIntegration({
    slackIntegrations,
    slackAvailable,
    isStaff,
    showSlackInstructions,
    requiredScopes,
    authorizeUrl,
    centered,
    slackAppManifest,
    onConnectClick,
    onShowInstructions,
}: {
    slackIntegrations: IntegrationType[] | null | undefined
    slackAvailable: boolean | undefined
    isStaff: boolean
    showSlackInstructions: boolean
    requiredScopes: string
    authorizeUrl: string
    centered?: boolean
    slackAppManifest: string
    onConnectClick: (() => void) | undefined
    onShowInstructions: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {slackIntegrations?.map((integration) => (
                <IntegrationView key={integration.id} integration={integration} schema={{ requiredScopes }} />
            ))}

            {slackAvailable ? (
                <div className={centered ? 'flex flex-col items-center gap-2 text-center' : 'flex flex-col gap-2'}>
                    <LinkPrimitive to={authorizeUrl} disableClientSideRouting onClick={onConnectClick}>
                        <img
                            alt="Connect to Slack workspace"
                            height="40"
                            width="139"
                            src="https://platform.slack-edge.com/img/add_to_slack.png"
                            srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                        />
                    </LinkPrimitive>
                    <Text size="xs" variant="muted" render={<p className={centered ? 'm-0 max-w-sm' : 'm-0'} />}>
                        Adding PostHog creates a public #posthog-inbox channel in your Slack workspace, where PostHog
                        posts what it finds.
                    </Text>
                </div>
            ) : isStaff ? (
                !showSlackInstructions ? (
                    <div>
                        <Button variant="outline" onClick={onShowInstructions}>
                            Show Instructions
                        </Button>
                    </div>
                ) : (
                    <div className="flex flex-col gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            To get started
                        </Heading>
                        <Text size="xs" render={<ol className="m-0 flex list-decimal flex-col gap-1 pl-4" />}>
                            <li>Copy the below Slack App Template</li>
                            <li>
                                Go to{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to="https://api.slack.com/apps" target="_blank" />}
                                >
                                    Slack Apps
                                </Button>
                            </li>
                            <li>Create an App using the provided template</li>
                            <li>
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.instanceSettings()} />}
                                >
                                    Go to Instance Settings
                                </Button>{' '}
                                and update the <code>"SLACK_"</code> properties using the values from the{' '}
                                <b>App Credentials</b> section of your Slack Apps
                            </li>
                        </Text>
                        <CodeSnippet language={Language.JSON}>{slackAppManifest}</CodeSnippet>
                    </div>
                )
            ) : (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    This PostHog instance is not configured for Slack. Please contact the instance owner to configure
                    it.
                </Text>
            )}
        </div>
    )
}
