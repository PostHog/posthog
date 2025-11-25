import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

interface SignupReferralSourceProps {
    disabledReason?: string
}

export default function SignupReferralSource({ disabledReason }: SignupReferralSourceProps): JSX.Element {
    return (
        <LemonField name="referral_source" label="Where did you hear about us?" showOptional>
            <LemonInput
                className="ph-ignore-input"
                data-attr="signup-referral-source"
                placeholder=""
                disabledReason={disabledReason}
            />
        </LemonField>
    )
}
