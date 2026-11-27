import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonLabel, LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, ItemDescription, Skeleton } from '@posthog/quill'

import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { QuillCustomerAnalyticsTaskDigest } from './QuillCustomerAnalyticsTaskDigest'
import { taskDigestLogic } from './taskDigestLogic'

const CADENCE_OPTIONS = [
    { value: 'weekdays' as const, label: 'Weekdays' },
    { value: 'every_day' as const, label: 'Every day' },
]

function formatTimeLabel(hour: number, minute: number): string {
    return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`
}

const TIME_OPTIONS = Array.from({ length: 48 }, (_, index) => {
    const hour = Math.floor(index / 2)
    const minute = (index % 2) * 30
    return {
        value: `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
        label: formatTimeLabel(hour, minute),
    }
})

export function CustomerAnalyticsTaskDigest({ source = 'settings' }: { source?: 'tasks' | 'settings' }): JSX.Element {
    const { draft, hasChanges, configLoading, isInitialLoading, configLoadFailed, timezone, validSendTime } =
        useValues(taskDigestLogic)
    const { setDraft, resetDraft, saveTaskDigest, loadConfig } = useActions(taskDigestLogic)
    const todayRailNav = useQuillSurface()
    const [hour, minute] = draft.send_time.split(':').map(Number)
    const timeOptions =
        validSendTime && !TIME_OPTIONS.some(({ value }) => value === draft.send_time)
            ? [
                  {
                      value: draft.send_time,
                      label: `${formatTimeLabel(hour, minute)} (current)`,
                      hidden: true,
                  },
                  ...TIME_OPTIONS,
              ]
            : TIME_OPTIONS

    const resetDisabledReason = configLoading ? 'Saving preferences' : hasChanges ? undefined : 'No changes'
    const saveDisabledReason = !validSendTime ? 'Choose a valid send time' : hasChanges ? undefined : 'No changes'

    const handleSave = (): void => saveTaskDigest({ source })

    if (isInitialLoading) {
        return todayRailNav ? <Skeleton className="h-20 w-full" /> : <LemonSkeleton className="h-20 w-full" />
    }

    if (configLoadFailed) {
        if (todayRailNav) {
            return (
                <Item tone="destructive" size="sm" className="flex-wrap">
                    <ItemContent>
                        <ItemDescription>Couldn't load your task digest preferences.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={loadConfig} loading={configLoading}>
                            Try again
                        </Button>
                    </ItemActions>
                </Item>
            )
        }

        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadConfig, loading: configLoading }}>
                Couldn't load your task digest preferences.
            </LemonBanner>
        )
    }

    if (todayRailNav) {
        return (
            <QuillCustomerAnalyticsTaskDigest
                timeOptions={timeOptions}
                cadenceOptions={CADENCE_OPTIONS}
                resetDisabledReason={resetDisabledReason}
                saveDisabledReason={saveDisabledReason}
                onSave={handleSave}
            />
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
                        <LemonSelect
                            id="task-digest-send-time"
                            aria-label="Send time"
                            disabled={configLoading}
                            value={draft.send_time}
                            options={timeOptions}
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
                <LemonButton type="secondary" onClick={resetDraft} disabledReason={resetDisabledReason}>
                    Clear changes
                </LemonButton>
                <LemonButton
                    data-attr="save-customer-analytics-task-digest"
                    type="primary"
                    onClick={handleSave}
                    loading={configLoading}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
