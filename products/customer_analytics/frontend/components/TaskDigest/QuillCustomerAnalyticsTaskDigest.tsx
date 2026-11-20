import { useActions, useValues } from 'kea'

import {
    Button,
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { TaskDigestDraft, taskDigestLogic } from './taskDigestLogic'

export interface TaskDigestOption<T extends string> {
    value: T
    label: string
    hidden?: boolean
}

export interface QuillCustomerAnalyticsTaskDigestProps {
    timeOptions: TaskDigestOption<string>[]
    cadenceOptions: TaskDigestOption<TaskDigestDraft['cadence']>[]
    resetDisabledReason: string | undefined
    saveDisabledReason: string | undefined
    onSave: () => void
}

export function QuillCustomerAnalyticsTaskDigest({
    timeOptions,
    cadenceOptions,
    resetDisabledReason,
    saveDisabledReason,
    onSave,
}: QuillCustomerAnalyticsTaskDigestProps): JSX.Element {
    const { draft, configLoading, timezone } = useValues(taskDigestLogic)
    const { setDraft, resetDraft } = useActions(taskDigestLogic)

    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" render={<p className="m-0" />}>
                Get an email summary of the customer tasks assigned to you. Each team member sets their own preferences.
            </Text>

            <div className="flex flex-row flex-wrap gap-4">
                <Field className="w-auto">
                    <FieldLabel htmlFor="task-digest-send-time">Send at</FieldLabel>
                    <div className="flex flex-row flex-wrap items-center gap-2">
                        <Select
                            value={draft.send_time}
                            onValueChange={(send_time) => send_time && setDraft({ send_time: send_time as string })}
                            disabled={configLoading}
                        >
                            <SelectTrigger
                                id="task-digest-send-time"
                                aria-label="Send time"
                                data-attr="task-digest-send-time"
                            >
                                <SelectValue>
                                    {(value: string) => timeOptions.find((option) => option.value === value)?.label}
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {timeOptions
                                    .filter((option) => !option.hidden)
                                    .map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                            </SelectContent>
                        </Select>
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {timezone}
                        </Text>
                    </div>
                </Field>

                <Field className="w-auto">
                    <FieldLabel htmlFor="task-digest-cadence">How often</FieldLabel>
                    <Select
                        value={draft.cadence}
                        onValueChange={(cadence) =>
                            cadence && setDraft({ cadence: cadence as TaskDigestDraft['cadence'] })
                        }
                        disabled={configLoading}
                    >
                        <SelectTrigger id="task-digest-cadence" data-attr="task-digest-cadence">
                            <SelectValue>
                                {(value: string) => cadenceOptions.find((option) => option.value === value)?.label}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {cadenceOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>
            </div>

            <QuillSettingSwitch
                label="Enable email digest"
                checked={draft.enabled}
                onCheckedChange={(enabled) => setDraft({ enabled })}
                disabled={configLoading}
            />

            <div className="flex flex-row flex-wrap gap-2 pt-2">
                <Button variant="outline" onClick={resetDraft} disabledReason={resetDisabledReason}>
                    Clear changes
                </Button>
                <Button
                    data-attr="save-customer-analytics-task-digest"
                    variant="primary"
                    onClick={onSave}
                    loading={configLoading}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </Button>
            </div>
        </div>
    )
}
