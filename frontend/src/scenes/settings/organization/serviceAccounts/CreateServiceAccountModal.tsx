import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { ServiceAccountsLogicProps, serviceAccountsLogic } from './serviceAccountsLogic'

export function CreateServiceAccountModal(props: ServiceAccountsLogicProps): JSX.Element {
    const logic = serviceAccountsLogic(props)
    const { creating, isNewAccountSubmitting, createFailed } = useValues(logic)
    const { setCreating, submitNewAccount } = useActions(logic)

    return (
        <LemonModal
            title="Create service account"
            isOpen={creating}
            onClose={() => !isNewAccountSubmitting && setCreating(false)}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => setCreating(false)}
                        disabledReason={isNewAccountSubmitting ? 'Creating service account' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitNewAccount}
                        loading={isNewAccountSubmitting}
                        data-attr="service-account-create-submit"
                    >
                        Create service account
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={serviceAccountsLogic}
                props={props}
                formKey="newAccount"
                enableFormOnSubmit
                className="space-y-4"
            >
                <p>
                    Give an integration or automation its own identity. The account uses your organization's default
                    project access.
                </p>
                <LemonField name="name" label="Name">
                    <LemonInput
                        autoFocus
                        maxLength={150}
                        placeholder="e.g. Release automation"
                        disabled={isNewAccountSubmitting}
                    />
                </LemonField>
                {createFailed && (
                    <LemonBanner type="error">
                        Couldn't create the service account. Check the name and try again.
                    </LemonBanner>
                )}
            </Form>
        </LemonModal>
    )
}
