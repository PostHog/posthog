import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SSFSettingsLogicProps, ssfSettingsLogic } from './ssfSettingsLogic'

type Props = SSFSettingsLogicProps & { disabledReason?: string | null }

export function SSFSubjectModal({ organizationId, disabledReason }: Props): JSX.Element {
    const logic = ssfSettingsLogic({ organizationId })
    const { subjectOpen, isSubjectSubmitting } = useValues(logic)
    const { closeSubject, setSubjectValue, submitSubject } = useActions(logic)
    return (
        <LemonModal isOpen={subjectOpen} onClose={closeSubject} title="Manage subject subscriptions">
            <Form logic={ssfSettingsLogic} props={{ organizationId }} formKey="subject" className="space-y-4 max-w-140">
                <p>
                    Add or remove the subject whose events this stream should deliver. Incoming changes are sent to the
                    transmitter through its stream management API.
                </p>
                <LemonField name="subjectJson" label="Subject identifier (JSON)">
                    <LemonTextArea
                        placeholder='{"format": "email", "email": "member@example.com"}'
                        minRows={4}
                        className="ph-no-capture"
                        disabled={!!disabledReason}
                        data-attr="ssf-subject-json"
                    />
                </LemonField>
                <div className="flex justify-end gap-2 flex-wrap">
                    <LemonButton
                        type="secondary"
                        onClick={closeSubject}
                        disabledReason={isSubjectSubmitting ? 'Wait for this request to finish.' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        loading={isSubjectSubmitting}
                        disabledReason={disabledReason}
                        onClick={() => {
                            setSubjectValue('remove', true)
                            submitSubject()
                        }}
                        data-attr="ssf-remove-subject"
                    >
                        Remove subject
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isSubjectSubmitting}
                        disabledReason={disabledReason}
                        onClick={() => {
                            setSubjectValue('remove', false)
                            submitSubject()
                        }}
                        data-attr="ssf-add-subject"
                    >
                        Add subject
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}
