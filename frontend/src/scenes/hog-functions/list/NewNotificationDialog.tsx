import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { HogFunctionSubTemplateIdType } from '~/types'

import {
    DESTINATION_OPTIONS,
    NewNotificationDialogLogicProps,
    newNotificationDialogLogic,
} from './newNotificationDialogLogic'

export interface NewNotificationDialogProps {
    /** The sub-template ID that defines the filters, name, and message templates */
    subTemplateId: HogFunctionSubTemplateIdType
    /** Callback fired after a notification is successfully created */
    onCreated: () => void
    /** Dialog title shown in the modal header */
    title?: string
    /** Override the default filters used by the sub-template */
    filtersOverride?: NewNotificationDialogLogicProps['filtersOverride']
}

export function NewNotificationDialog({
    subTemplateId,
    onCreated,
    title = 'New notification',
    filtersOverride,
}: NewNotificationDialogProps): JSX.Element {
    const logicProps: NewNotificationDialogLogicProps = { subTemplateId, onCreated, filtersOverride }
    const logic = newNotificationDialogLogic(logicProps)

    const {
        isOpen,
        notificationForm,
        isNotificationFormSubmitting,
        notificationFormHasErrors,
        selectedSlackIntegration,
    } = useValues(logic)
    const { closeDialog, setNotificationFormValue } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeDialog}
            title={title}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeDialog}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form="new-notification-form"
                        htmlType="submit"
                        disabledReason={notificationFormHasErrors ? 'Please fill in the required fields' : undefined}
                        loading={isNotificationFormSubmitting}
                    >
                        Create
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={newNotificationDialogLogic}
                props={logicProps}
                formKey="notificationForm"
                id="new-notification-form"
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-4">
                    <Field name="destination" label="Destination">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={(val) => {
                                    onChange(val)
                                    setNotificationFormValue('webhookUrl', '')
                                }}
                                options={DESTINATION_OPTIONS.map((d) => ({
                                    value: d.value,
                                    label: d.label,
                                    icon: <img src={d.iconUrl} alt="" className="h-5 w-5 object-contain" />,
                                }))}
                                fullWidth
                            />
                        )}
                    </Field>

                    {notificationForm.destination === 'slack' && (
                        <>
                            <Field name="slackIntegrationId" label="Slack workspace">
                                {({ value, onChange }) => (
                                    <IntegrationChoice
                                        integration="slack"
                                        value={value ?? undefined}
                                        onChange={(val) => {
                                            onChange(val)
                                            setNotificationFormValue('slackChannel', null)
                                        }}
                                    />
                                )}
                            </Field>
                            {selectedSlackIntegration && (
                                <Field name="slackChannel" label="Channel">
                                    {({ value, onChange }) => (
                                        <SlackChannelPicker
                                            value={value ?? undefined}
                                            onChange={onChange}
                                            integration={selectedSlackIntegration}
                                        />
                                    )}
                                </Field>
                            )}
                        </>
                    )}

                    {notificationForm.destination === 'discord' && (
                        <Field name="webhookUrl" label="Discord webhook URL">
                            {({ value, onChange }) => (
                                <LemonInput
                                    value={value}
                                    onChange={onChange}
                                    placeholder="https://discord.com/api/webhooks/..."
                                    fullWidth
                                />
                            )}
                        </Field>
                    )}

                    {notificationForm.destination === 'microsoft-teams' && (
                        <Field name="webhookUrl" label="Microsoft Teams webhook URL">
                            {({ value, onChange }) => (
                                <LemonInput value={value} onChange={onChange} placeholder="https://..." fullWidth />
                            )}
                        </Field>
                    )}

                    {notificationForm.destination === 'webhook' && (
                        <Field name="webhookUrl" label="Webhook URL">
                            {({ value, onChange }) => (
                                <LemonInput value={value} onChange={onChange} placeholder="https://..." fullWidth />
                            )}
                        </Field>
                    )}
                </div>
            </Form>
        </LemonModal>
    )
}
