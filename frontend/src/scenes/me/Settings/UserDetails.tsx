import React from 'react'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Form } from 'kea-forms'
import { IconWarning } from 'lib/components/icons'
import { Link } from '@posthog/lemon-ui'

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
                {({ onChange, value }) => (
                    <>
                        {!!user?.pending_email && (
                            <div className="flex items-center text-warning">
                                <IconWarning className="text-2xl mr-2" />
                                <b>
                                    Change from "{user.email}" pending verification.{' '}
                                    <Link onClick={resendVerificationEmail}>Resend email.</Link>
                                </b>
                            </div>
                        )}
                        <LemonInput
                            className="ph-ignore-input"
                            data-attr="settings-update-email"
                            placeholder="email@yourcompany.com"
                            disabled={userLoading}
                            onChange={onChange}
                            value={value}
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
