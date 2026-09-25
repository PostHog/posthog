import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { ACCOUNT_ID_FIELDS, customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountEditModal(): JSX.Element {
    const { account, accountEditorOpen, accountFormHasErrors, isAccountFormSubmitting } = useValues(
        customerAnalyticsAccountSceneLogic
    )
    const { closeAccountEditor, submitAccountForm } = useActions(customerAnalyticsAccountSceneLogic)

    return (
        <LemonModal
            isOpen={accountEditorOpen}
            onClose={isAccountFormSubmitting ? undefined : closeAccountEditor}
            title="Edit account"
            width={600}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAccountEditor}
                        disabledReason={isAccountFormSubmitting ? 'Saving account' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitAccountForm}
                        loading={isAccountFormSubmitting}
                        disabledReason={accountFormHasErrors ? 'Enter a valid account name' : undefined}
                        data-attr="save-account-name"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={customerAnalyticsAccountSceneLogic} formKey="accountForm" enableFormOnSubmit>
                <div className="flex flex-col gap-4">
                    <LemonField name="name" label="Name">
                        <LemonInput autoFocus fullWidth maxLength={400} />
                    </LemonField>
                    <LemonDivider className="my-0" />
                    <h3 className="mb-0">Account IDs</h3>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                        {ACCOUNT_ID_FIELDS.filter(
                            (field) => field.key !== 'stripe_customer_id' || account?.properties?.stripe_customer_id
                        ).map((field) => (
                            <LemonField key={field.key} name={field.key} label={field.label}>
                                <LemonInput fullWidth placeholder={field.placeholder} />
                            </LemonField>
                        ))}
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
