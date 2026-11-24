import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Button, Input, Text } from '@posthog/quill'

import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'
import { emailChangeVerificationLogic } from 'scenes/settings/user/emailChangeVerificationLogic'
import { EmailChangeVerificationModal } from 'scenes/settings/user/EmailChangeVerificationModal'
import { userLogic } from 'scenes/userLogic'

const NAME_AND_EMAIL_FIELDS = [
    { name: 'first_name', label: 'First name', dataAttr: 'settings-update-first-name', placeholder: 'Jane' },
    { name: 'last_name', label: 'Last name', dataAttr: 'settings-update-last-name', placeholder: 'Doe' },
    { name: 'email', label: 'Email', dataAttr: 'settings-update-email', placeholder: 'email@yourcompany.com' },
]

export function QuillUserDetails(): JSX.Element {
    const { userLoading, isUserDetailsSubmitting, userDetailsChanged, user } = useValues(userLogic)
    const { cancelEmailChangeRequest } = useActions(userLogic)
    const { openModal } = useActions(emailChangeVerificationLogic)

    return (
        <>
            <EmailChangeVerificationModal />
            <Form logic={userLogic} formKey="userDetails" enableFormOnSubmit className="flex flex-col gap-4 max-w-md">
                {NAME_AND_EMAIL_FIELDS.map(({ name, label, dataAttr, placeholder }) => (
                    <QuillSettingFormField key={name} name={name} label={label}>
                        {({ id, value, onChange, invalid }) => (
                            <Input
                                id={id}
                                value={value ?? ''}
                                onChange={(event) => onChange(event.target.value)}
                                aria-invalid={invalid}
                                className="ph-ignore-input"
                                data-attr={dataAttr}
                                placeholder={placeholder}
                                disabled={userLoading}
                            />
                        )}
                    </QuillSettingFormField>
                ))}
                {user?.pending_email && (
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" variant="destructive" weight="medium" render={<span className="m-0" />}>
                            Pending verification for {user.pending_email}
                        </Text>
                        <Button size="xs" data-attr="enter-email-verification-code-button" onClick={openModal}>
                            Enter verification code
                        </Button>
                        <Button
                            size="xs"
                            data-attr="cancel-email-change-request-button"
                            onClick={cancelEmailChangeRequest}
                        >
                            Cancel change
                        </Button>
                    </div>
                )}
                <div>
                    <Button
                        variant="primary"
                        type="submit"
                        loading={isUserDetailsSubmitting}
                        disabledReason={userDetailsChanged ? undefined : 'No changes to save'}
                        data-attr="user-details-submit-bottom"
                    >
                        Save name and email
                    </Button>
                </div>
            </Form>
        </>
    )
}
