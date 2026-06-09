import type { AuthFlowVariant } from './authFlowVariants'
import { LegacyInviteSignup } from './invite-signup/variants/legacy/LegacyInviteSignup'
import { InviteSignupV2 } from './invite-signup/variants/redesign-2026-06-02/InviteSignupV2'
import { LegacyLogin } from './login/variants/legacy/LegacyLogin'
import { LoginV2 } from './login/variants/redesign-2026-06-02/LoginV2'
import { LegacySignup } from './signup/variants/legacy/LegacySignup'
import { SignupV2 } from './signup/variants/redesign-2026-06-02/SignupV2'

interface AuthFlowVariantComponents {
    Login: () => JSX.Element | null
    Signup: () => JSX.Element | null
    InviteSignup: () => JSX.Element | null
}

// One variant value selects login, signup and invited signup together.
export const authFlowVariantRegistry: Record<AuthFlowVariant, AuthFlowVariantComponents> = {
    legacy: { Login: LegacyLogin, Signup: LegacySignup, InviteSignup: LegacyInviteSignup },
    'redesign-2026-06-02': { Login: LoginV2, Signup: SignupV2, InviteSignup: InviteSignupV2 },
}
