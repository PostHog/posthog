import React from 'react'
import { useValues } from 'kea'
import { Divider } from 'antd'
import { JSSnippet } from 'lib/components/JSSnippet'
import { InviteTeam } from 'lib/components/InviteTeam'
import { OptOutCapture } from './OptOutCapture'
import { UpdateEmailPreferences } from './UpdateEmailPreferences'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'

import { userLogic } from 'scenes/userLogic'
import { DeleteDemoData } from './DeleteDemoData'
import { SlackIntegration } from 'scenes/setup/SlackIntegration'
import { ChangePassword } from './ChangePassword'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'

export function Setup() {
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
            <a href="https://posthog.com/docs/integrations">Using Python/Ruby/Node/Go/PHP/iOS/Android instead?</a>
            <Divider />
            <h2 id="apikey">API key</h2>
            You can use this api key in any of our
            <a href="https://posthog.com/docs/integrations"> libraries</a>.
            <pre className="code">{user.team.api_token}</pre>
            This key is write-only, in that it can only create new events. It can't read any events or any of your other
            data stored on PostHog.
            <Divider />
            <h2 id="urls">Permitted domains</h2>
            These are the domains and urls where the toolbar will automatically open if you're logged in. It's also the
            domains where you'll be able to create actions on.
            <EditAppUrls />
            <Divider />
            <h2 id="slack">Slack or Teams Integration</h2>
            <SlackIntegration />
            <Divider />
            <h2 id="invite">Invite your team</h2>
            <div className="row">
                <div className="col-lg-6">
                    <InviteTeam user={user} />
                </div>
            </div>
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
            <h2>Security and feature updates</h2>
            <UpdateEmailPreferences />
        </div>
    )
}
