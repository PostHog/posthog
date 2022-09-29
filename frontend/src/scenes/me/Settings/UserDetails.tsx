import React from 'react'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Form } from 'kea-forms'
import { Link } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'

export function UserDetails(): JSX.Element {
    const { user, userLoading, isUserDetailsSubmitting, userDetailsChanged } = useValues(userLogic)
    const { resendVerificationEmail } = useActions(userLogic)

    return (
        <Form
            logic={userLogic}
            formKey="userDetails"
            enableFormOnSubmit
            className="space-y-4"
            style={{
                maxWidth: '30rem',
            }}
        >
            <Field name="first_name" label="Your name">
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="settings-update-first-name"
                    placeholder="Jane Doe"
                    disabled={userLoading}
                />
            </Field>

            <Field name="email" label="Your email">
                {(passedProps) => (
                    <>
                        {!!user?.pending_email && (
                            <AlertMessage type="warning">
                                Change to "{user.pending_email}" is pending verification. Check your inbox for
                                the verification message. (<Link onClick={resendVerificationEmail}>Resend</Link>)
                            </AlertMessage>
                        )}
                        <LemonInput
                            className="ph-ignore-input"
                            data-attr="settings-update-email"
                            placeholder="email@yourcompany.com"
                            disabled={userLoading}
                            {...passedProps}
                        />
                    </>
                )}
            </Field>

            <LemonButton
                type="primary"
                htmlType="submit"
                loading={isUserDetailsSubmitting}
                disabled={!userDetailsChanged}
                data-attr="user-details-submit-bottom"
            >
                Save name and email
            </LemonButton>
        </Form>
    )
}
