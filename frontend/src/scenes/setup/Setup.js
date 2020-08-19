import React from 'react'
import { useValues } from 'kea'
import { Divider } from 'antd'
import { IPCapture } from './IPCapture'
import { JSSnippet } from 'lib/components/JSSnippet'
import { OptOutCapture } from './OptOutCapture'
import { UpdateEmailPreferences } from './UpdateEmailPreferences'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'

import { userLogic } from 'scenes/userLogic'
import { DeleteDemoData } from './DeleteDemoData'
import { WebhookIntegration } from 'scenes/setup/WebhookIntegration'
import { ChangePassword } from './ChangePassword'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { hot } from 'react-hot-loader/root'
import { ToolbarSettings } from 'scenes/setup/ToolbarSettings'

export const Setup = hot(_Setup)
function _Setup() {
    const { user } = useValues(userLogic)
    const { location } = useValues(router)

    useAnchor(location.hash)

    return (
        <div>
            <h2 id="snippet">Integrate PostHog</h2>
            To integrate PostHog, copy + paste the following snippet to your website. Ideally, put it just above the{' '}
            <pre style={{ display: 'inline' }}>&lt;/head&gt;</pre> tag.{' '}
            <a href="https://posthog.com/docs/integrations/js-integration">
                See docs for instructions on how to identify users.
            </a>
            <JSSnippet user={user} />
            <h2 id="custom events">Send Custom Events</h2>
            To send custom events visit our <a href="https://posthog.com/docs/integrations">docs</a> and integrate the
            library in specific language you're building in (Python/Ruby/Node/Go/PHP/iOS/Android etc.) <Divider />
            <h2 id="apikey">API key</h2>
            You can use this api key in any of our
            <a href="https://posthog.com/docs/integrations"> libraries</a>.
            <pre className="code">{user.team.api_token}</pre>
            This key is write-only, in that it can only create new events. It can't read any events or any of your other
            data stored on PostHog.
            <Divider />
            <h2 id="urls">Permitted Domains/URLs</h2>
            These are the domains and URLs where the Toolbar will automatically open if you're logged in. It's also
            where you'll be able to create Actions.
            <EditAppUrls />
            <Divider />
            <h2 id="webhook">Slack / Microsoft Teams Integration</h2>
            <WebhookIntegration />
            <Divider />
            <h2 id="demodata">Delete HogFlix demo data</h2>
            <DeleteDemoData />
            <Divider />
            <h2 id="password">Change Password</h2>
            <ChangePassword />
            <Divider />
            <h2 id="optout">Anonymize data collection</h2>
            <OptOutCapture />
            <Divider />
            <h2 id="datacapture">Data capture configuration</h2>
            <IPCapture />
            <Divider />
            <h2>Security and feature updates</h2>
            <UpdateEmailPreferences />
            <Divider />
            <h2>
                PostHog Toolbar (<span style={{ color: 'red' }}>BETA</span>)
            </h2>
            <ToolbarSettings />
        </div>
    )
}
