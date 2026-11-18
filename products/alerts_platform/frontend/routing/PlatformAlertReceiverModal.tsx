import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { IncidentIoReceiverFields } from './IncidentIoReceiverFields'
import { PagerDutyReceiverFields } from './PagerDutyReceiverFields'
import { RECEIVER_TYPE_OPTIONS } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'
import { SlackReceiverFields } from './SlackReceiverFields'
import { WebhookReceiverFields } from './WebhookReceiverFields'

export function PlatformAlertReceiverModal(): JSX.Element {
    const { receiverModalOpen, editingReceiver, receiverForm, isReceiverFormSubmitting } =
        useValues(platformAlertRoutingLogic)
    const { closeReceiverModal, submitReceiverForm } = useActions(platformAlertRoutingLogic)

    return (
        <LemonModal
            isOpen={receiverModalOpen}
            onClose={closeReceiverModal}
            title={editingReceiver ? 'Edit receiver' : 'New receiver'}
            description="A receiver is a destination that routes send matching alerts to."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeReceiverModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitReceiverForm}
                        loading={isReceiverFormSubmitting}
                        data-attr="platform-alert-receiver-save"
                    >
                        {editingReceiver ? 'Save' : 'Add receiver'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={platformAlertRoutingLogic}
                formKey="receiverForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Infra on-call" data-attr="platform-alert-receiver-name" />
                </LemonField>
                <LemonField name="type" label="Type">
                    <LemonSelect options={RECEIVER_TYPE_OPTIONS} fullWidth data-attr="platform-alert-receiver-type" />
                </LemonField>
                {receiverForm.type === 'slack' ? (
                    <SlackReceiverFields />
                ) : receiverForm.type === 'pagerduty' ? (
                    <PagerDutyReceiverFields />
                ) : receiverForm.type === 'incident_io' ? (
                    <IncidentIoReceiverFields />
                ) : (
                    <WebhookReceiverFields />
                )}
            </Form>
        </LemonModal>
    )
}
