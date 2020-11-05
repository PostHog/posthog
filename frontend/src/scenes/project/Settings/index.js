import React from 'react'
import { useActions, useValues } from 'kea'
import { Card, Divider } from 'antd'
import { IPCapture } from './IPCapture'
import { JSSnippet } from 'lib/components/JSSnippet'
import { OptInSessionRecording } from './OptInSessionRecording'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { userLogic } from 'scenes/userLogic'
import { WebhookIntegration } from './WebhookIntegration'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { ReloadOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { hot } from 'react-hot-loader/root'
import { ToolbarSettings } from './ToolbarSettings'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'

export const Setup = hot(_Setup)
function _Setup() {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)
    const { location } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)

    useAnchor(location.hash)

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader title={`Project Settings – ${user.team.name}`} />
            <Card>
                <h2 id="snippet" className="subtitle">
                    Website Event Autocapture
                </h2>
                To integrate PostHog into your webiste and get event autocapture with no additional work, include the
                following snippet in your&nbsp;website's&nbsp;HTML. Ideally, put it just above the&nbsp;
                <code>{'<head>'}</code>&nbsp;tag.
                <br />
                For more guidance, including on identying users,{' '}
                <a href="https://posthog.com/docs/integrations/js-integration">see PostHog Docs</a>.
                <JSSnippet />
                <Divider />
                <h2 id="custom-events" className="subtitle">
                    Send Custom Events
                </h2>
                To send custom events <a href="https://posthog.com/docs/integrations">visit PostHog Docs</a> and
                integrate the library for the specific language or platform you're using. We support Python, Ruby, Node,
                Go, PHP, iOS, Android, and more.
                <Divider />
                <h2 id="project-api-key" className="subtitle">
                    Project API Key
                </h2>
                You can use this write-only key in any one of{' '}
                <a href="https://posthog.com/docs/integrations">our libraries</a>.
                <CodeSnippet
                    actions={[
                        {
                            Icon: ReloadOutlined,
                            popconfirmProps: {
                                title: 'Reset project API key, invalidating the current one?',
                                okText: 'Reset Key',
                                okType: 'danger',
                                icon: <ReloadOutlined style={{ color: red.primary }} />,
                                placement: 'left',
                            },
                            callback: resetToken,
                        },
                    ]}
                >
                    {currentTeam?.api_token}
                </CodeSnippet>
                Write-only means it can only create new events. It can't read events or any of your other data stored
                with PostHog, so it's safe to use in public apps.
                <Divider />
                <h2 id="urls" className="subtitle">
                    Permitted Domains/URLs
                </h2>
                <p>
                    These are the domains and URLs where the Toolbar will automatically open if you're logged in. It's
                    also where you'll be able to create Actions.
                </p>
                <EditAppUrls />
                <Divider />
                <h2 id="webhook" className="subtitle">
                    Slack / Microsoft Teams Integration
                </h2>
                <WebhookIntegration />
                <Divider />
                <h2 id="datacapture" className="subtitle">
                    Data Capture Configuration
                </h2>
                <IPCapture />
                <Divider />
                <h2 className="subtitle">PostHog Toolbar</h2>
                <ToolbarSettings />
                <Divider />
                {(!user.is_multi_tenancy || featureFlags['session-recording-player']) && (
                    <>
                        <h2 id="sessionrecording" className="subtitle">
                            Session recording <span style={{ fontSize: 16, color: 'var(--warning)' }}>BETA</span>
                        </h2>
                        <p>
                            Watch sessions replays to see how users interact with your app and find out what can be
                            improved.
                        </p>
                        <OptInSessionRecording />
                        <br />
                        <p>
                            This is a new feature of PostHog. Please{' '}
                            <a href="https://github.com/PostHog/posthog/issues/new/choose" target="_blank">
                                share feedback
                            </a>{' '}
                            with us!
                        </p>
                    </>
                )}
            </Card>
        </div>
    )
}
