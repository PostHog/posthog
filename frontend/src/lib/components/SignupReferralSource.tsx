import { LemonField, LemonInput } from '@posthog/lemon-ui'

export default function SignupReferralSource({ disabled }: { disabled: boolean }): JSX.Element {
    return (
        <LemonField name="referral_source" label="Where did you hear about us?" showOptional>
            <LemonInput
                className="ph-ignore-input"
                data-attr="signup-referral-source"
                placeholder=""
                disabled={disabled}
            />
        </LemonField>
    )
}
