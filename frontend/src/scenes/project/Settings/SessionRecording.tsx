import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Input, Switch } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export function SessionRecording(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { preflight } = useValues(preflightLogic)

    const [period, setPeriod] = useState(null as null | number)

    useEffect(() => setPeriod(currentTeam?.session_recording_retention_period_days ?? null), [currentTeam])

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <Switch
                    // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                    id="opt-in-session-recording-switch"
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({ session_recording_opt_in: checked })
                    }}
                    checked={currentTeam?.session_recording_opt_in}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                    htmlFor="opt-in-session-recording-switch"
                >
                    Record user sessions on Permitted Domains
                </label>
            </div>

            {currentTeam?.session_recording_opt_in && !preflight?.cloud && (
                <>
                    <div style={{ marginBottom: 8 }}>
                        <Switch
                            data-attr="session-recording-retention-period-switch"
                            onChange={(checked) => {
                                const newPeriod = checked ? 7 : null
                                updateCurrentTeam({ session_recording_retention_period_days: newPeriod })
                                setPeriod(newPeriod)
                            }}
                            checked={period != null}
                        />
                        <label
                            style={{
                                marginLeft: '10px',
                            }}
                        >
                            Automatically delete old session recordings{period !== null && ' after'}
                        </label>
                    </div>
                    {period !== null && (
                        <div style={{ maxWidth: '15rem', marginLeft: 54 }}>
                            <Input
                                type="number"
                                addonAfter="days"
                                onChange={(event) => {
                                    const newPeriod = parseFloat(event.target.value)
                                    setPeriod(newPeriod)
                                }}
                                onBlur={() =>
                                    updateCurrentTeam({
                                        session_recording_retention_period_days: period,
                                    })
                                }
                                onPressEnter={(e) => (e.target as HTMLInputElement).blur()}
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
