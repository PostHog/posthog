import type { AuthFlowVariant } from './authFlowVariants'
import { LegacyInviteSignup } from './invite-signup/variants/legacy/LegacyInviteSignup'
import { PaperDeskInviteSignup } from './invite-signup/variants/paper-desk/PaperDeskInviteSignup'
import { LegacyLogin } from './login/variants/legacy/LegacyLogin'
import { PaperDeskLogin } from './login/variants/paper-desk/PaperDeskLogin'
import { LegacySignup } from './signup/variants/legacy/LegacySignup'
import { PaperDeskSignup } from './signup/variants/paper-desk/PaperDeskSignup'
import { LegacyVerifyEmail } from './verify-email/variants/legacy/LegacyVerifyEmail'
import { PaperDeskVerifyEmail } from './verify-email/variants/paper-desk/PaperDeskVerifyEmail'

interface AuthFlowVariantComponents {
    Login: () => JSX.Element | null
    Signup: () => JSX.Element | null
    InviteSignup: () => JSX.Element | null
    VerifyEmail: () => JSX.Element | null
}

// One variant value selects every auth-flow screen together: login, signup, invited signup and email verification.
export const authFlowVariantRegistry: Record<AuthFlowVariant, AuthFlowVariantComponents> = {
    legacy: {
        Login: LegacyLogin,
        Signup: LegacySignup,
        InviteSignup: LegacyInviteSignup,
        VerifyEmail: LegacyVerifyEmail,
    },
    'paper-desk': {
        Login: PaperDeskLogin,
        Signup: PaperDeskSignup,
        InviteSignup: PaperDeskInviteSignup,
        VerifyEmail: PaperDeskVerifyEmail,
    },
}
