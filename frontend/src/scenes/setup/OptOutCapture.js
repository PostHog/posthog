import React, { useState } from 'react'
import { useValues } from 'kea'
import api from '../../lib/api'
import { userLogic } from '../userLogic'

export function OptOutCapture() {
    const { user } = useValues(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            PostHog uses PostHog (unsurprisingly!) to capture information about
            how people are using the product. We believe that product analytics
            are the best way to make PostHog more useful for everyone.
            <br />
            <br />
            We also understand there are many reasons why people don't want to
            or aren't allowed to send this usage data. Just tick the box below
            to opt out of this.
            <br />
            <br />
            <label>
                <input
                    type="checkbox"
                    onChange={e => {
                        api.update('api/user', {
                            team: { opt_out_capture: e.target.checked },
                        }).then(() => setSaved(true))
                    }}
                    defaultChecked={user.team.opt_out_capture}
                />
                &nbsp;Tick this box to <strong>opt-out</strong> of sending usage
                data to PostHog.
            </label>
            {saved && (
                <p className="text-success">
                    Preference saved.{' '}
                    <a href="/setup">
                        Refresh the page for the change to take effect.
                    </a>
                </p>
            )}
            <br />
            <br />
        </div>
    )
}
