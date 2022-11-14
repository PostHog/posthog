import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Form } from 'kea-forms'

export function UserDetails(): JSX.Element {
    const { userLoading, isUserDetailsSubmitting, userDetailsChanged } = useValues(userLogic)

    return (
        <Form
            logic={userLogic}
            formKey="userDetails"
            enableFormOnSubmit
            className="space-y-4"
            style={{
                maxWidth: '28rem',
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
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="settings-update-email"
                    placeholder="email@yourcompany.com"
                    disabled={userLoading}
                />
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
