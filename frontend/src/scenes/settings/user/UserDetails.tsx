import { LemonTag } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
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
            <LemonField name="first_name" label="First name">
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="settings-update-first-name"
                    placeholder="Jane"
                    disabled={userLoading}
                />
            </LemonField>

            <LemonField name="last_name" label="Last name">
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="settings-update-last-name"
                    placeholder="Doe"
                    disabled={userLoading}
                />
            </LemonField>

            <LemonField name="email" label="Email">
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="settings-update-email"
                    placeholder="email@yourcompany.com"
                    disabled={userLoading}
                />
            </LemonField>
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
