import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

interface SignupRoleSelectProps {
    className?: string
    disabledReason?: string
}

export default function SignupRoleSelect({ className, disabledReason }: SignupRoleSelectProps): JSX.Element {
    return (
        <LemonField name="role_at_organization" label="What is your role?" className={className}>
            <LemonSelect
                fullWidth
                data-attr="signup-role-at-organization"
                disabledReason={disabledReason}
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
