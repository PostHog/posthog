import React from 'react'
import { Input } from 'antd'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'

export function UserDetails(): JSX.Element {
    const { userLoading, isUserDetailsSubmitting } = useValues(userLogic)

    return (
        <Form
            logic={userLogic}
            formKey="userDetails"
            className="ant-form-vertical ant-form-hide-required-mark"
            style={{
                maxWidth: 400,
            }}
        >
            <Field name="first_name" label="Name">
                {({ value, onChange }) => (
                    <Input
                        className="ph-ignore-input"
                        autoFocus
                        data-attr="settings-update-first-name"
                        placeholder="Jane Doe"
                        disabled={userLoading}
                        value={value}
                        onChange={onChange}
                    />
                )}
            </Field>

            <LemonButton
                type="primary"
                htmlType="submit"
                loading={isUserDetailsSubmitting}
                data-attr="user-details-submit-bottom"
            >
                Update Details
            </LemonButton>
        </Form>
    )
}
