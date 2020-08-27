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
import { CodeSnippet } from 'scenes/onboarding/FrameworkInstructions/CodeSnippet'
import { PersonalAPIKeys } from 'lib/components/PersonalAPIKeys'

export const Setup = hot(_Setup)
function _Setup() {
    const { user } = useValues(userLogic)
    const { location } = useValues(router)

    useAnchor(location.hash)

    return (
        <div>
            <h2 id="snippet">Integrate PostHog</h2>
            To integrate PostHog, copy and paste the following snippet to your website. Ideally, put it just above the{' '}
            <pre style={{ display: 'inline' }}>&lt;/head&gt;</pre> tag.{' '}
            <a href="https://posthog.com/docs/integrations/js-integration">
                See docs for instructions on how to identify users.
            </a>
            <JSSnippet user={user} />
            <h2 id="custom-events">Send Custom Events</h2>
            To send custom events <a href="https://posthog.com/docs/integrations">visit our docs</a> and integrate the
            library for the specific language or platform you're using (Python, Ruby, Node, Go, PHP, iOS, Android, and
            more).
            <Divider />
            <h2 id="team-api-key">Team API Key</h2>
            You can use this write-only key in any one of{' '}
            <a href="https://posthog.com/docs/integrations">our libraries</a>.
            <CodeSnippet>{user.team.api_token}</CodeSnippet>
            Write-only means it can only create new events. It can't read events or any of your other data stored with
            PostHog, so it's safe to use in public apps. Still, if possible, include it in the build as an environment
            variable instead of hard-coding.
            <Divider />
            <h2 id="personal-api-keys">Personal API Keys</h2>
            <PersonalAPIKeys />
            <Divider />
            <h2 id="urls">Permitted Domains/URLs</h2>
            These are the domains and URLs where the Toolbar will automatically open if you're logged in. It's also
            where you'll be able to create Actions.
            <EditAppUrls />
            <Divider />
            <h2 id="webhook">Slack / Microsoft Teams Integration</h2>
            <WebhookIntegration />
            <Divider />
            <h2 id="demodata">Delete HogFlix Demo Data</h2>
            <DeleteDemoData />
            <Divider />
            <h2 id="password">Change Password</h2>
            <ChangePassword />
            <Divider />
            <h2 id="optout">Anonymize Data Collection</h2>
            <OptOutCapture />
            <Divider />
            <h2 id="datacapture">Data Capture Configuration</h2>
            <IPCapture />
            <Divider />
            <h2>Security and Feature Updates</h2>
            <UpdateEmailPreferences />
            <Divider />
            <h2>
                PostHog Toolbar <span style={{ color: 'red' }}>[BETA]</span>
            </h2>
            <ToolbarSettings />
        </div>
    )
}
