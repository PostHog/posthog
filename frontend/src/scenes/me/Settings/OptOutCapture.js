import React, { useState } from 'react'
import { useValues } from 'kea'
import { Switch } from 'antd'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

export function OptOutCapture() {
    const { user } = useValues(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            <p>
                PostHog uses PostHog (unsurprisingly!) to capture information about how people are using the product. We
                believe that product analytics is crucial to making PostHog the most useful it can be, for everyone.
            </p>
            <p>
                We also understand there are many reasons why people don't want to or aren't allowed to send this usage
                data. If you would like to anonymize your personal usage data, just tick the box below.
            </p>
            <Switch
                id="anonymize-data-collection"
                onChange={(checked) => {
                    api.update('api/user', {
                        user: {
                            anonymize_data: checked,
                        },
                    }).then(() => setSaved(true))
                }}
                defaultChecked={user.anonymize_data}
            />
            <label
                htmlFor="anonymize-data-collection"
                style={{
                    marginLeft: '10px',
                }}
            >
                Anonymize my data.
            </label>
            {saved && (
                <p className="text-success">
                    Preference saved. <a href="/my/settings">Refresh the page for the change to take effect.</a>
                </p>
            )}
        </div>
    )
}
