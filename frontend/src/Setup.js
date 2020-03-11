import React from 'react'
import { useValues } from 'kea'
import { JSSnippet } from './utils';
import InviteTeam from './InviteTeam';
import OptOutCapture from './OptOutCapture'

import { userLogic } from './userLogic'
import SetupAppUrls from './SetupAppUrls'

export default function Setup () {
    const { user } = useValues(userLogic)

    return (
        <div>
            <h1>Setup your PostHog account</h1>

            <SetupAppUrls />
            <br /><br />

            <h2>Integrate PostHog</h2>
            To integrate PostHog, copy + paste the following snippet to your website. Ideally, put it just above the <pre style={{display: 'inline'}}>&lt;/head&gt;</pre> tag.
            <a href='https://github.com/PostHog/posthog/wiki/JS-integration'>See docs for instructions on how to identify users.</a><br /><br />
            <JSSnippet user={user} />
            <a href='https://github.com/PostHog/posthog/wiki/Integrations'>Using Python/Ruby/Node/Go/PHP instead?</a><br /><br />
            <br /><br />

            <h2>Invite your team</h2>
            <div className='row'>
                <div className='col-lg-6'>
                    <InviteTeam user={user} />
                </div>
            </div>
            <br /><br />

            <h2>Opt out of capturing</h2>
            <OptOutCapture />
        </div>
    )
}
