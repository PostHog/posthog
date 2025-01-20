import { LemonField } from '@posthog/lemon-ui'
import { LemonSelect } from '@posthog/lemon-ui'

export default function SignupRoleSelect({ className }: { className?: string }): JSX.Element {
    return (
        <LemonField name="role_at_organization" label="What is your role?" className={className}>
            <LemonSelect
                fullWidth
                data-attr="signup-role-at-organization"
                options={[
                    {
                        label: 'Engineering',
                        value: 'engineering',
                    },
                    {
                        label: 'Data',
                        value: 'data',
                    },
                    {
                        label: 'Product Management',
                        value: 'product',
                    },
                    {
                        label: 'Founder',
                        value: 'founder',
                    },
                    {
                        label: 'Leadership',
                        value: 'leadership',
                    },
                    {
                        label: 'Marketing',
                        value: 'marketing',
                    },
                    {
                        label: 'Sales / Success',
                        value: 'sales',
                    },
                    {
                        label: 'Other',
                        value: 'other',
                    },
                ]}
            />
        </LemonField>
    )
}
