import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { taskDigestLogic } from './taskDigestLogic'

const CADENCE_OPTIONS = [
    { value: 'weekdays' as const, label: 'Weekdays' },
    { value: 'every_day' as const, label: 'Every day' },
]

export function CustomerAnalyticsTaskDigest(): JSX.Element {
    const { draft, hasChanges, configLoading, isInitialLoading, configLoadFailed, timezone, validSendTime } =
        useValues(taskDigestLogic)
    const { setDraft, resetDraft, saveTaskDigest, loadConfig } = useActions(taskDigestLogic)

    if (isInitialLoading) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    if (configLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadConfig, loading: configLoading }}>
                Couldn't load your task digest preferences.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="mb-0">
                Get an email summary of the customer tasks assigned to you. Each team member sets their own preferences.
            </p>

            <div className="flex flex-row flex-wrap gap-4">
                <div className="flex flex-col gap-2">
                    <LemonLabel htmlFor="task-digest-send-time">Send at</LemonLabel>
                    <div className="flex flex-row flex-wrap items-center gap-2">
                        <LemonInput
                            id="task-digest-send-time"
                            type="time"
                            className="w-36"
                            disabled={configLoading}
                            value={draft.send_time}
                            onChange={(send_time) => setDraft({ send_time })}
                            data-attr="task-digest-send-time"
                        />
                        <span className="text-secondary">{timezone}</span>
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <LemonLabel htmlFor="task-digest-cadence">How often</LemonLabel>
                    <LemonSelect
                        id="task-digest-cadence"
                        disabled={configLoading}
                        value={draft.cadence}
                        options={CADENCE_OPTIONS}
                        onChange={(cadence) => setDraft({ cadence })}
                        data-attr="task-digest-cadence"
                    />
                </div>
            </div>

            <LemonSwitch
                checked={draft.enabled}
                onChange={(enabled) => setDraft({ enabled })}
                label="Enable email digest"
                bordered
                disabled={configLoading}
            />

            <div className="flex flex-row flex-wrap gap-2 pt-2">
                <LemonButton
                    type="secondary"
                    onClick={resetDraft}
                    disabledReason={configLoading ? 'Saving preferences' : hasChanges ? undefined : 'No changes'}
                >
                    Clear changes
                </LemonButton>
                <LemonButton
                    data-attr="save-customer-analytics-task-digest"
                    type="primary"
                    onClick={saveTaskDigest}
                    loading={configLoading}
                    disabledReason={!validSendTime ? 'Choose a valid send time' : hasChanges ? undefined : 'No changes'}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
