// Detail strings raised by `enforce_two_factor` (posthog/helpers/two_factor_session.py) when an
// org enforces 2FA and the member has no device or an unverified session. The gate has dedicated
// UI — the setup modal and the re-authentication toast in apiStatusLogic — so call sites that catch
// the 403 and toast `error.detail` would only add a stale, contradictory red toast. LemonToast drops
// these at a single choke point instead.
const TWO_FACTOR_GATE_DETAILS = ['2FA setup required', '2FA verification required']

// Stable id for the gate toast so twoFactorLogic can dismiss any outstanding one on setup success.
export const TWO_FACTOR_GATE_TOAST_ID = 'two-factor-gate'

// Matches both the raw detail and messages that append it (e.g. "Failed to update organization: 2FA
// setup required"), so a call site that wraps the detail is suppressed the same way as one that passes
// it directly.
export function isTwoFactorGateDetail(message: unknown): boolean {
    return typeof message === 'string' && TWO_FACTOR_GATE_DETAILS.some((detail) => message.endsWith(detail))
}
