import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { Input, Switch } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function SessionRecording(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    const [period, setPeriod] = useState(user?.team?.session_recording_retention_period_days || null)

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <Switch
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        userUpdateRequest({ team: { session_recording_opt_in: checked } })
                    }}
                    checked={user?.team?.session_recording_opt_in}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                >
                    Record user sessions on Permitted Domains
                </label>
            </div>

            {user?.team?.session_recording_opt_in && !user.is_multi_tenancy && (
                <>
                    <div style={{ marginBottom: 8 }}>
                        <Switch
                            data-attr="session-recording-retention-period-switch"
                            onChange={(checked) => {
                                const newPeriod = checked ? 7 : null
                                userUpdateRequest({ team: { session_recording_retention_period_days: newPeriod } })
                                setPeriod(newPeriod)
                            }}
                            checked={period != null}
                        />
                        <label
                            style={{
                                marginLeft: '10px',
                            }}
                        >
                            Automatically delete old session recordings after
                        </label>
                    </div>
                    {period != null && (
                        <div style={{ maxWidth: '15rem', marginLeft: 54 }}>
                            <Input
                                type="number"
                                addonAfter="days"
                                onChange={(event) => {
                                    const newPeriod = parseFloat(event.target.value)
                                    userUpdateRequest({ team: { session_recording_retention_period_days: newPeriod } })
                                    setPeriod(newPeriod)
                                }}
                                value={period}
                                placeholder="Retention period"
                            />
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
