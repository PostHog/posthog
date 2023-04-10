import { useActions, useValues } from 'kea'
import { supportLogic } from './supportLogic'
import { Field, Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect/LemonSelect'

export default function SupportForm(): JSX.Element {
    const { isSupportFormOpen } = useValues(supportLogic)
    const { closeSupportForm } = useActions(supportLogic)
    const TargetAreaToName = {
        analytics: 'Analytics',
        apps: 'Apps',
        billing: 'Billing',
        feature_flags: 'Feature Flags',
        ingestion: 'Ingestion',
        session_reply: 'Session Replay',
    }

    return (
        <LemonModal
            isOpen={isSupportFormOpen}
            onClose={closeSupportForm}
            title={'Bug / Feedback / Question'}
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
                <div className="flex gap-2">
                    <Field name="kind" label="Kind">
                        <LemonSelect
                            options={['bug', 'feedback', 'question'].map((key) => {
                                return {
                                    value: key,
                                    label: key,
                                }
                            })}
                        />
                    </Field>
                    <Field name="target_area" label="Target Area">
                        <LemonSelect
                            options={Object.entries(TargetAreaToName).map(([key, value]) => {
                                return {
                                    label: value,
                                    value: key,
                                }
                            })}
                        />
                    </Field>
                </div>
                <Field name="message" label="Content">
                    <LemonTextArea placeholder="Type your message here" data-attr="support-form-content-input" />
                </Field>
            </Form>
        </LemonModal>
    )
}
