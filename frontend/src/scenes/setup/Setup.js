import React from 'react'
import { useValues } from 'kea'
import { JSSnippet } from '../../lib/utils'
import { InviteTeam } from '../../lib/components/InviteTeam'
import { OptOutCapture } from './OptOutCapture'
import { UpdateEmailPreferences } from './UpdateEmailPreferences'
import { SetupAppUrls } from './SetupAppUrls'

import { userLogic } from '../userLogic'
import { DeleteDemoData } from './DeleteDemoData'
import { SlackIntegration } from 'scenes/setup/SlackIntegration'
import { ChangePassword } from './ChangePassword'

export function Setup() {
    const { user } = useValues(userLogic)

    return (
        <div>
            <h1>Setup your PostHog account</h1>
            <SetupAppUrls />
            <br />
            <br />
            <h2>Integrate PostHog</h2>
            To integrate PostHog, copy + paste the following snippet to your website. Ideally, put it just above the{' '}
            <pre style={{ display: 'inline' }}>&lt;/head&gt;</pre> tag.
            <a href="https://docs.posthog.com/#/integrations/js-integration">
                See docs for instructions on how to identify users.
            </a>
            <br />
            <JSSnippet user={user} />
            <a href="https://docs.posthog.com/#/integrations">Using Python/Ruby/Node/Go/PHP instead?</a>
            <br />
            <br />
            <br />
            <h2>API key</h2>
            You can use this api key in any of our
            <a href="https://docs.posthog.com/#/integrations"> libraries</a>.
            <pre className="code">{user.team.api_token}</pre>
            This key is write-only, in that it can only create new events. It can't read any events or any of your other
            data stored on PostHog.
            <br />
            <br />
            <br />
            <h2>Slack Integration</h2>
            <SlackIntegration />
            <br />
            <br />
            <h2>Invite your team</h2>
            <div className="row">
                <div className="col-lg-6">
                    <InviteTeam user={user} />
                </div>
            </div>
            <br />
            <br />
            <h2>Delete HogFlix demo data</h2>
            <DeleteDemoData />
            <br />
            <br />
            <br />
            <h2>Change Password</h2>
            <ChangePassword />
            <br />
            <br />
            <br />
            <h2>Opt out of capturing</h2>
            <OptOutCapture />
            <br />
            <br />
            <br />
            <h2>Security and feature updates</h2>
            <UpdateEmailPreferences />
        </div>
    )
}
