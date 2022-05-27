import React from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Field } from 'lib/forms/Field'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'

export function UserDetails(): JSX.Element {
    const { userLoading, isUserDetailsSubmitting } = useValues(userLogic)

    return (
        <VerticalForm
            logic={userLogic}
            formKey="userDetails"
            enableFormOnSubmit
            style={{
                maxWidth: 400,
            }}
        >
            <Field name="first_name" label="Your name">
                <LemonInput
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="settings-update-first-name"
                    placeholder="Jane Doe"
                    disabled={userLoading}
                />
            </Field>

            <LemonButton
                type="primary"
                htmlType="submit"
                loading={isUserDetailsSubmitting}
                data-attr="user-details-submit-bottom"
            >
                Save name
            </LemonButton>
        </VerticalForm>
    )
}
