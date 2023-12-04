import { LemonTag } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { userLogic } from 'scenes/userLogic'

export function UserDetails(): JSX.Element {
    const { userLoading, isUserDetailsSubmitting, userDetailsChanged, user } = useValues(userLogic)

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
            {user?.pending_email && <LemonTag type="highlight">Pending verification for {user.pending_email}</LemonTag>}

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
