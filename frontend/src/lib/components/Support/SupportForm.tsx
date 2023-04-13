import { useActions, useValues } from 'kea'
import { supportLogic } from './supportLogic'
import { Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { Field } from 'lib/forms/Field'
import { capitalizeFirstLetter } from 'lib/utils'

export default function SupportForm(): JSX.Element {
    const { isSupportFormOpen } = useValues(supportLogic)
    const { closeSupportForm } = useActions(supportLogic)
    const TargetAreaToName = {
        analytics: 'Analytics',
        apps: 'Apps',
        billing: 'Billing',
        cohorts: 'Cohorts',
        data_management: 'Data Management',
        ingestion: 'Events Ingestion',
        experiments: 'Experiments',
        feature_flags: 'Feature Flags',
        login: 'Login / Sign up / Invites',
        session_reply: 'Session Replay',
    }

    return (
        <LemonModal
            isOpen={isSupportFormOpen}
            onClose={closeSupportForm}
            title={'Bug / Feedback'}
            description="Submit a request to our helpdesk"
            footer={
                <div className="flex-1 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <LemonButton form="support-modal-form" type="secondary" onClick={closeSupportForm}>
                            Cancel
                        </LemonButton>
                        <LemonButton form="support-modal-form" htmlType="submit" type="primary" data-attr="submit">
                            Submit
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={supportLogic}
                formKey="sendSupportRequest"
                id="support-modal-form"
                enableFormOnSubmit
                className="space-y-4"
            >
                <Field name="kind" label="What kind of request is this?">
                    <LemonSelect
                        fullWidth
                        options={['bug', 'feedback'].map((key) => ({
                            value: key,
                            label: capitalizeFirstLetter(key),
                        }))}
                    />
                </Field>
                <Field name="target_area" label="What area does it best relate to?">
                    <LemonSelect
                        fullWidth
                        options={Object.entries(TargetAreaToName).map(([key, value]) => ({
                            label: value,
                            value: key,
                        }))}
                    />
                </Field>
                <Field name="message" label="Content">
                    <LemonTextArea placeholder="Type your message here" data-attr="support-form-content-input" />
                </Field>
            </Form>
        </LemonModal>
    )
}
