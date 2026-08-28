import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { ReminderApi, ReminderStatusEnumApi } from 'products/reminders/frontend/generated/api.schemas'

import { remindersLogic } from './remindersLogic'

const RECURRENCE_OPTIONS = [
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' },
    { value: 'yearly', label: 'Yearly' },
]

const STATUS_TAG_TYPE: Record<ReminderStatusEnumApi, 'primary' | 'muted' | 'danger'> = {
    active: 'primary',
    completed: 'muted',
    errored: 'danger',
}

function scheduleSummary(reminder: ReminderApi): string {
    if (reminder.cron_expression) {
        return `Cron: ${reminder.cron_expression}`
    }
    if (reminder.recurrence_interval) {
        return capitalizeFirstLetter(reminder.recurrence_interval)
    }
    return 'One-off'
}

function ReminderModal(): JSX.Element {
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

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => setEditingReminderId(null)}
            title={isCreating ? 'New reminder' : 'Edit reminder'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setEditingReminderId(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitReminderForm}
                        loading={isReminderFormSubmitting}
                        data-attr="save-reminder"
                    >
                        {isCreating ? 'Create reminder' : 'Save'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={remindersLogic} formKey="reminderForm" className="deprecated-space-y-4">
                <LemonField name="title" label="Title">
                    <LemonInput placeholder="Review the activation dashboard" maxLength={255} autoFocus />
                </LemonField>
                <LemonField name="message" label="Message" info="Optional longer text shown in the notification.">
                    <LemonTextArea placeholder="Optional details" minRows={2} />
                </LemonField>
                <LemonField name="team" label="Project">
                    {({ value, onChange }) => (
                        <LemonSelect value={value} onChange={onChange} options={projectOptions} fullWidth />
                    )}
                </LemonField>

                <LemonField name="scheduleType" label="Schedule">
                    {({ value, onChange }) => (
                        <LemonSegmentedButton
                            value={value}
                            onChange={onChange}
                            disabledReason={!isScheduleEditable ? 'This reminder has already fired' : undefined}
                            options={[
                                { value: 'one-off', label: 'One-off' },
                                { value: 'repeats', label: 'Repeats' },
                                { value: 'advanced', label: 'Advanced' },
                            ]}
                            fullWidth
                        />
                    )}
                </LemonField>

                {reminderForm.scheduleType === 'one-off' && (
                    <LemonField name="scheduled_at" label="Fires at">
                        {({ value, onChange }) => (
                            <DatePicker
                                value={value ? dayjs(value) : null}
                                onChange={(date) => onChange(date ? date.toISOString() : null)}
                                granularity="minute"
                                placeholder="Select date and time"
                                maxDate={dayjs().add(10, 'year')}
                                disabledReason={!isScheduleEditable ? 'This reminder has already fired' : undefined}
                            />
                        )}
                    </LemonField>
                )}

                {reminderForm.scheduleType === 'repeats' && (
                    <LemonField name="recurrence_interval" label="Repeats every">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={RECURRENCE_OPTIONS}
                                placeholder="Select an interval"
                                disabled={!isScheduleEditable}
                                fullWidth
                            />
                        )}
                    </LemonField>
                )}

                {reminderForm.scheduleType === 'advanced' && (
                    <LemonField
                        name="cron_expression"
                        label="Cron expression"
                        info="5-field cron, max 4 fires per day."
                    >
                        <LemonInput placeholder="0 9 * * 1" disabled={!isScheduleEditable} />
                    </LemonField>
                )}

                {reminderForm.scheduleType !== 'one-off' && (
                    <LemonField name="end_date" label="Ends" info="Optional. The reminder stops after this time.">
                        {({ value, onChange }) => (
                            <DatePicker
                                value={value ? dayjs(value) : null}
                                onChange={(date) => onChange(date ? date.toISOString() : null)}
                                granularity="minute"
                                placeholder="No end date"
                                clearable
                                maxDate={dayjs().add(10, 'year')}
                                disabledReason={!isScheduleEditable ? 'This reminder has already fired' : undefined}
                            />
                        )}
                    </LemonField>
                )}

                <LemonField name="timezone" label="Time zone">
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="single"
                            value={[value]}
                            onChange={(newTimezones) => newTimezones[0] && onChange(newTimezones[0])}
                            options={timezoneOptions}
                            placeholder="Select a time zone"
                            disabled={!isScheduleEditable}
                            virtualized
                        />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}

export function Reminders(): JSX.Element {
    const { reminders, remindersLoading } = useValues(remindersLogic)
    const { setEditingReminderId, deleteReminder } = useActions(remindersLogic)

    return (
        <div className="flex flex-col gap-4">
            <div>
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => setEditingReminderId('new')}
                    data-attr="new-reminder"
                >
                    New reminder
                </LemonButton>
            </div>

            <LemonTable
                loading={remindersLoading}
                dataSource={reminders}
                rowKey="id"
                emptyState="No reminders yet. Create one to get a nudge when it's due."
                columns={[
                    {
                        title: 'Title',
                        dataIndex: 'title',
                        render: (_, reminder) => <span className="font-semibold">{reminder.title}</span>,
                    },
                    {
                        title: 'Schedule',
                        render: (_, reminder) => scheduleSummary(reminder),
                    },
                    {
                        title: 'Next fire',
                        render: (_, reminder) =>
                            reminder.next_fire_at ? <TZLabel time={reminder.next_fire_at} /> : '—',
                    },
                    {
                        title: 'Status',
                        render: (_, reminder) => (
                            <LemonTag type={STATUS_TAG_TYPE[reminder.status]}>
                                {capitalizeFirstLetter(reminder.status)}
                            </LemonTag>
                        ),
                    },
                    {
                        title: '',
                        width: 0,
                        render: (_, reminder) => (
                            <div className="flex gap-1 justify-end">
                                <LemonButton
                                    size="small"
                                    icon={<IconPencil />}
                                    tooltip="Edit"
                                    onClick={() => setEditingReminderId(reminder.id)}
                                />
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    tooltip="Delete"
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: 'Delete reminder?',
                                            description: `"${reminder.title}" will be permanently deleted.`,
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deleteReminder(reminder.id),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }
                                />
                            </div>
                        ),
                    },
                ]}
            />

            <ReminderModal />
        </div>
    )
}
