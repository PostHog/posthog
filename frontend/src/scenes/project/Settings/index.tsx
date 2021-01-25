import React from 'react'
import { useActions, useValues } from 'kea'
import { Card, Divider, Tag } from 'antd'
import { IPCapture } from './IPCapture'
import { JSSnippet } from 'lib/components/JSSnippet'
import { SessionRecording } from './SessionRecording'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { WebhookIntegration } from './WebhookIntegration'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { ReloadOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { hot } from 'react-hot-loader/root'
import { ToolbarSettings } from './ToolbarSettings'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { DangerZone } from './DangerZone'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/components/Link'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { userLogic } from 'scenes/userLogic'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'

export const Setup = hot(_Setup)
function _Setup(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)
    const { location } = useValues(router)
    const { user } = useValues(userLogic)

    const { shareFeedbackCommand } = useActions(commandPaletteLogic)

    useAnchor(location.hash)

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader title={`Project Settings${user ? `– ${user.team?.name}` : ''}`} />
            <Card>
                <h2 id="snippet" className="subtitle">
                    Website Event Autocapture
                </h2>
                To integrate PostHog into your website and get event autocapture with no additional work, include the
                following snippet in your&nbsp;website's&nbsp;HTML. Ideally, put it just above the&nbsp;
                <code>{'<head>'}</code>&nbsp;tag.
                <br />
                For more guidance, including on identying users,{' '}
                <a href="https://posthog.com/docs/integrations/js-integration">see PostHog Docs</a>.
                <JSSnippet />
                <p>
                    You can even test PostHog out on a live site without changing any code.
                    <br />
                    Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on
                    and click it.
                    <br />
                    This will enable our tracking, on the currently loaded page only. The data will show up in this
                    project.
                    <br />
                </p>
                <p>{user?.team && <JSBookmarklet team={user.team} />}</p>
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
                <h2 className="subtitle" id="urls">
                    Permitted Domains/URLs
                </h2>
                <p>
                    These are the domains and URLs where the Toolbar will automatically open if you're logged in. It's
                    also where you'll be able to create Actions and record sessions.
                </p>
                <EditAppUrls />
                <Divider />
                <h2 className="subtitle" id="webhook">
                    Webhook Integration
                </h2>
                <WebhookIntegration />
                <Divider />
                <h2 className="subtitle" id="datacapture">
                    Data Capture Configuration
                </h2>
                <IPCapture />
                <Divider />
                <h2 className="subtitle">PostHog Toolbar</h2>
                <ToolbarSettings />
                <Divider />
                <h2 id="session-recording" className="subtitle" style={{ display: 'flex', alignItems: 'center' }}>
                    Session Recording
                    <Tag color="orange" style={{ marginLeft: 8 }}>
                        BETA
                    </Tag>
                </h2>
                <p>
                    Watch sessions replays to see how users interact with your app and find out what can be improved.
                    You can watch recorded sessions in the <Link to="/sessions">sessions page</Link>. Please note{' '}
                    <b>your website needs to have</b> the <a href="#snippet">PostHog snippet</a> or the latest version
                    of{' '}
                    <a
                        href="https://posthog.com/docs/integrations/js-integration?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        posthog-js
                    </a>{' '}
                    installed.
                </p>
                <SessionRecording />
                <p>
                    This is a new feature of PostHog. Please{' '}
                    <a onClick={() => shareFeedbackCommand('How can we improve session recording?')}>share feedback</a>{' '}
                    with us!
                </p>
                <Divider />
                <h2 style={{ color: 'var(--danger)' }} className="subtitle">
                    Danger Zone
                </h2>
                <DangerZone />
            </Card>
        </div>
    )
}
