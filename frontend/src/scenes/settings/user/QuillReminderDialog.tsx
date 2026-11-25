import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    FieldDescription,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Textarea,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { dayjs } from 'lib/dayjs'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { RECURRENCE_OPTIONS } from './reminderSchedule'
import { remindersLogic } from './remindersLogic'

const SCHEDULE_TYPE_OPTIONS = [
    { value: 'one-off', label: 'One-off' },
    { value: 'repeats', label: 'Repeats' },
    { value: 'advanced', label: 'Advanced' },
]

export function QuillReminderDialog(): JSX.Element {
    const {
        editingReminderId,
        reminderForm,
        isReminderFormSubmitting,
        isScheduleEditable,
        projectOptions,
        timezoneOptions,
    } = useValues(remindersLogic)
    const { setEditingReminderId, submitReminderForm } = useActions(remindersLogic)

    const isOpen = editingReminderId !== null
    const isCreating = editingReminderId === 'new'
    const scheduleLockedReason = !isScheduleEditable ? 'This reminder has already fired' : undefined
    const timezoneLabels = new Map(timezoneOptions.map((option) => [option.key, option.label]))

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    setEditingReminderId(null)
                }
            }}
        >
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>{isCreating ? 'New reminder' : 'Edit reminder'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Form logic={remindersLogic} formKey="reminderForm" className="flex flex-col gap-4">
                        <QuillSettingFormField name="title" label="Title">
                            {({ id, value, onChange, invalid }) => (
                                <Input
                                    id={id}
                                    value={value ?? ''}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder="Review the activation dashboard"
                                    maxLength={255}
                                    autoFocus
                                    aria-invalid={invalid || undefined}
                                />
                            )}
                        </QuillSettingFormField>

                        <QuillSettingFormField name="message" label="Message">
                            {({ id, value, onChange, invalid }) => (
                                <>
                                    <Textarea
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="Optional details"
                                        rows={2}
                                        aria-invalid={invalid || undefined}
                                    />
                                    <FieldDescription>Optional longer text shown in the notification.</FieldDescription>
                                </>
                            )}
                        </QuillSettingFormField>

                        <QuillSettingFormField name="team" label="Project">
                            {({ id, value, onChange }) => (
                                <Select items={projectOptions} value={value} onValueChange={onChange}>
                                    <SelectTrigger id={id} className="w-full">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {projectOptions.map((option) => (
                                            <SelectItem key={option.value ?? 'organization'} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            )}
                        </QuillSettingFormField>

                        <QuillSettingFormField name="scheduleType" label="Schedule">
                            {({ id, value, onChange }) => (
                                <ToggleGroup
                                    id={id}
                                    variant="outline"
                                    aria-label="Schedule"
                                    value={[value]}
                                    onValueChange={(next: string[]) => next[0] && onChange(next[0])}
                                    className="w-full"
                                >
                                    {SCHEDULE_TYPE_OPTIONS.map((option) => (
                                        <ToggleGroupItem
                                            key={option.value}
                                            value={option.value}
                                            disabledReason={scheduleLockedReason}
                                            className="flex-1"
                                        >
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
                            )}
                        </QuillSettingFormField>

                        {reminderForm.scheduleType === 'one-off' && (
                            <QuillSettingFormField name="scheduled_at" label="Fires at">
                                {({ value, onChange }) => (
                                    <DatePicker
                                        value={value ? dayjs(value) : null}
                                        onChange={(date) => onChange(date ? date.toISOString() : null)}
                                        granularity="minute"
                                        placeholder="Select date and time"
                                        maxDate={dayjs().add(10, 'year')}
                                        disabledReason={scheduleLockedReason}
                                    />
                                )}
                            </QuillSettingFormField>
                        )}

                        {reminderForm.scheduleType === 'repeats' && (
                            <QuillSettingFormField name="recurrence_interval" label="Repeats every">
                                {({ id, value, onChange }) => (
                                    <Select items={RECURRENCE_OPTIONS} value={value} onValueChange={onChange}>
                                        <SelectTrigger id={id} className="w-full" disabledReason={scheduleLockedReason}>
                                            <SelectValue placeholder="Select an interval" />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {RECURRENCE_OPTIONS.map((option) => (
                                                <SelectItem key={option.value} value={option.value}>
                                                    {option.label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                )}
                            </QuillSettingFormField>
                        )}

                        {reminderForm.scheduleType === 'advanced' && (
                            <QuillSettingFormField name="cron_expression" label="Cron expression">
                                {({ id, value, onChange, invalid }) => (
                                    <>
                                        <Input
                                            id={id}
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder="0 9 * * 1"
                                            disabledReason={scheduleLockedReason}
                                            aria-invalid={invalid || undefined}
                                        />
                                        <FieldDescription>5-field cron, max 4 fires per day.</FieldDescription>
                                    </>
                                )}
                            </QuillSettingFormField>
                        )}

                        {reminderForm.scheduleType !== 'one-off' && (
                            <QuillSettingFormField name="end_date" label="Ends">
                                {({ value, onChange }) => (
                                    <>
                                        <DatePicker
                                            value={value ? dayjs(value) : null}
                                            onChange={(date) => onChange(date ? date.toISOString() : null)}
                                            granularity="minute"
                                            placeholder="No end date"
                                            clearable
                                            maxDate={dayjs().add(10, 'year')}
                                            disabledReason={scheduleLockedReason}
                                        />
                                        <FieldDescription>
                                            Optional. The reminder stops after this time.
                                        </FieldDescription>
                                    </>
                                )}
                            </QuillSettingFormField>
                        )}

                        <QuillSettingFormField name="timezone" label="Time zone">
                            {({ id, value, onChange }) => (
                                <Combobox
                                    items={timezoneOptions.map((option) => option.key)}
                                    value={value || null}
                                    onValueChange={(next: string | null) => {
                                        if (next) {
                                            onChange(next)
                                        }
                                    }}
                                    itemToStringLabel={(timezone: string) => timezoneLabels.get(timezone) ?? timezone}
                                >
                                    <ComboboxInput
                                        id={id}
                                        placeholder="Select a time zone"
                                        disabledReason={scheduleLockedReason}
                                    />
                                    <ComboboxContent>
                                        <ComboboxEmpty>No matching time zones</ComboboxEmpty>
                                        <ComboboxList>
                                            {(timezone: string) => (
                                                <ComboboxItem key={timezone} value={timezone}>
                                                    {timezoneLabels.get(timezone) ?? timezone}
                                                </ComboboxItem>
                                            )}
                                        </ComboboxList>
                                    </ComboboxContent>
                                </Combobox>
                            )}
                        </QuillSettingFormField>
                    </Form>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setEditingReminderId(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitReminderForm}
                        loading={isReminderFormSubmitting}
                        data-attr="save-reminder"
                    >
                        {isCreating ? 'Create reminder' : 'Save'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
