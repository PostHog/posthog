import { Field } from 'lib/forms/Field'
import { LemonSelect } from './LemonSelect'

export default function SignupRoleSelect({ className }: { className?: string }): JSX.Element {
    return (
        <Field name="role_at_organization" label="What is your role?" className={className} showOptional>
            <LemonSelect
                fullWidth
                data-attr="signup-role-at-organization"
                options={[
                    {
                        label: 'Engineering',
                        value: 'engineering',
                    },
                    {
                        label: 'Product Management',
                        value: 'product',
                    },
                    {
                        label: 'Executive',
                        value: 'executive',
                    },
                    {
                        label: 'Customer Success',
                        value: 'customer-success',
                    },
                    {
                        label: 'Sales',
                        value: 'sales',
                    },
                    {
                        label: 'Other',
                        value: 'other',
                    },
                ]}
            />
        </Field>
    )
}
