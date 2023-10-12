import { LemonButton, LemonInput, LemonModal, LemonModalProps } from '@posthog/lemon-ui'
import { Field, Form } from 'kea-forms'
import { sourceModalLogic } from './sourceModalLogic'
import { useValues } from 'kea'

interface SourceModalProps extends LemonModalProps {}

export default function SourceModal(props: SourceModalProps): JSX.Element {
    const { isAirbyteResourceSubmitting } = useValues(sourceModalLogic)

    return (
        <LemonModal {...props} title="Data Sources" description="One click link a data source">
            {/* <LemonButton>
                Link Stripe
            </LemonButton> */}
            <Form logic={sourceModalLogic} formKey={'airbyteResource'} className="space-y-4" enableFormOnSubmit>
                <Field name="account_id" label="Account Id">
                    <LemonInput className="ph-ignore-input" autoFocus data-attr="account-id" placeholder="acct_" />
                </Field>
                <Field name="client_secret" label="Client Secret">
                    <LemonInput className="ph-ignore-input" autoFocus data-attr="client-secret" placeholder="sklive" />
                </Field>
                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="source-link"
                    loading={isAirbyteResourceSubmitting}
                >
                    Link
                </LemonButton>
            </Form>
        </LemonModal>
    )
}
