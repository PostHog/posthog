import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonCard, LemonInput, LemonLabel, LemonSwitch, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ConversationsSettings } from '~/types'

const DEFAULT_SPIKE_MULTIPLIER = 3
const DEFAULT_SPIKE_MIN_TICKETS = 5

/** Numeric setting input that buffers keystrokes locally and saves once, on blur or enter. */
function NumberSettingInput({
    value,
    min,
    max,
    step,
    disabled,
    onSave,
}: {
    value: number
    min: number
    max?: number
    step?: number
    disabled: boolean
    onSave: (value: number) => void
}): JSX.Element {
    const [draft, setDraft] = useState<number | undefined>(value)
    useEffect(() => setDraft(value), [value])

    const commit = (): void => {
        // A cleared number input emits NaN (not undefined); never persist it —
        // snap back to the saved value instead.
        if (draft == null || !Number.isFinite(draft)) {
            setDraft(value)
            return
        }
        if (draft !== value) {
            onSave(draft)
        }
    }

    return (
        <LemonInput
            type="number"
            min={min}
            max={max}
            step={step}
            value={draft}
            disabled={disabled}
            onChange={setDraft}
            onBlur={commit}
            onPressEnter={commit}
            className="w-32"
        />
    )
}

export function TrendsSection(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const settings = currentTeam?.conversations_settings ?? {}
    const trendsEnabled = settings.trends_enabled ?? true
    const notificationsEnabled = settings.trends_notifications_enabled ?? true
    const multiplier = settings.trends_spike_multiplier ?? DEFAULT_SPIKE_MULTIPLIER
    const minTickets = settings.trends_spike_min_tickets ?? DEFAULT_SPIKE_MIN_TICKETS

    const patchSettings = (patch: Partial<ConversationsSettings>): void => {
        updateCurrentTeam({
            conversations_settings: {
                ...settings,
                ...patch,
            },
        })
    }

    return (
        <div className="flex flex-col gap-4 max-w-[800px]">
            <LemonCard hoverEffect={false} className="flex flex-col gap-3 px-4 py-3">
                <LemonSwitch
                    label="Detect ticket trends and incidents"
                    checked={trendsEnabled}
                    disabled={currentTeamLoading}
                    onChange={(checked) => patchSettings({ trends_enabled: checked })}
                    bordered
                    fullWidth
                />
                <p className="text-xs text-muted-alt mb-0">
                    Watches ticket volume (overall and per channel, priority, or your own alert rules) and flags unusual
                    spikes as possible incidents. Review them on the <Link to={urls.supportTrends()}>Trends</Link> tab.
                    No AI required.
                </p>
            </LemonCard>

            <LemonCard hoverEffect={false} className="flex flex-col gap-3 px-4 py-3">
                <h4 className="font-semibold mb-0">Sensitivity</h4>
                <p className="text-xs text-muted-alt mb-1">
                    Built-in spike detection fires when ticket volume clears both thresholds. Higher values mean fewer,
                    more significant alerts. Custom alert rules can override these per rule.
                </p>
                <div className="flex gap-6">
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Spike multiplier</LemonLabel>
                        <NumberSettingInput
                            value={multiplier}
                            min={1.5}
                            max={100}
                            step={0.5}
                            disabled={!trendsEnabled || currentTeamLoading}
                            onSave={(value) => patchSettings({ trends_spike_multiplier: value })}
                        />
                        <span className="text-xs text-muted-alt">times the normal volume for that time of day</span>
                    </div>
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Minimum tickets</LemonLabel>
                        <NumberSettingInput
                            value={minTickets}
                            min={1}
                            disabled={!trendsEnabled || currentTeamLoading}
                            onSave={(value) => patchSettings({ trends_spike_min_tickets: value })}
                        />
                        <span className="text-xs text-muted-alt">before a spike can fire</span>
                    </div>
                </div>
            </LemonCard>

            <LemonCard hoverEffect={false} className="flex flex-col gap-3 px-4 py-3">
                <LemonSwitch
                    label="Notify the team in-app when an incident is detected"
                    checked={notificationsEnabled}
                    disabled={!trendsEnabled || currentTeamLoading}
                    onChange={(checked) => patchSettings({ trends_notifications_enabled: checked })}
                    bordered
                    fullWidth
                />
                <LemonBanner type="info" action={{ children: 'Add alert destination', to: urls.supportTrends() }}>
                    Want a Slack, Teams, or webhook alert too? Incidents fire the{' '}
                    <code>$conversation_incident_detected</code> event, and one-click destinations live on the Trends
                    tab.
                </LemonBanner>
            </LemonCard>
        </div>
    )
}
