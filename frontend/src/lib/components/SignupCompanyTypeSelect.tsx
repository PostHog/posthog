import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

interface SignupCompanyTypeSelectProps {
    className?: string
    disabledReason?: string
}

export default function SignupCompanyTypeSelect({
    className,
    disabledReason,
}: SignupCompanyTypeSelectProps): JSX.Element {
    return (
        <LemonField name="company_type" label="What type of company do you work for?" className={className}>
            <LemonSelect
                fullWidth
                data-attr="signup-company-type"
                disabledReason={disabledReason}
                options={[
                    {
                        label: 'B2B',
                        value: 'b2b',
                    },
                    {
                        label: 'B2C',
                        value: 'b2c',
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
