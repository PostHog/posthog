import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import api from './Api';
import { JSSnippet } from './utils';
import InviteTeam from './InviteTeam';
import OptOutCapture from './OptOutCapture'

import { userLogic } from './userLogic'

export default function Setup () {
    const [saved, setSaved] = useState(false)
    const { user } = useValues(userLogic)
    const { setUser } = useActions(userLogic)

    function addUrl () {
        user.team.app_urls.push('https://');
        setUser(user);
    }

    function removeUrl (index) {
        user.team.app_urls.splice(index, 1);
        setUser(user);
    }

    function updateUrl (index, value) {
        user.team.app_urls[index] = value;
        setUser(user);
    }

    function onSubmit (e) {
        e.preventDefault();
        api.update('api/user', {team: { app_urls: user.team.app_urls }}).then(response => {
            setSaved(true)
            user.team.app_urls = response.team.app_urls;
            setUser(user);
        })
    }

    const appUrls = user.team.app_urls || ['https://']

    return (
        <div>
            <h1>Setup your PostHog account</h1>
            <label>What URLs will you be using PostHog on?</label>
            <form onSubmit={onSubmit}>
                {appUrls.map((url, index) => (
                    <div key={index} style={{ marginBottom: 5 }}>
                        <input
                            defaultValue={url}
                            onChange={(e) => updateUrl(index, e.target.value)}
                            autoFocus
                            style={{ display: 'inline-block', maxWidth: 400 }}
                            type="url"
                            className='form-control'
                            name={`url${index}`}
                            placeholder="https://...."
                        />
                        {index > 0 ? <button className='btn btn-link' type="button" onClick={() => removeUrl(index)}>Remove</button> : null}
                    </div>
                ))}
                <button className='btn btn-link' type="button" onClick={addUrl} style={{ padding: '5px 0', marginBottom: 15 }}>+ Add Another URL</button>
                <br />

                <button className='btn btn-success' type="submit">Save URLs</button>
                {saved && <span className='text-success' style={{ marginLeft: 10 }}>URLs saved.</span>}
            </form>
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
