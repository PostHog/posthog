import { LemonInput } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'

export default function SignupReferralSource({ disabled }: { disabled: boolean }): JSX.Element {
    return (
        <Field name="referral_source" label="Where did you hear about us?" showOptional>
            <LemonInput
                className="ph-ignore-input"
                data-attr="signup-referral-source"
                placeholder=""
                disabled={disabled}
            />
        </Field>
    )
}
