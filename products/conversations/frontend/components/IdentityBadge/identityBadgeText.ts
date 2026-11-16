export const IDENTITY_DOCS_URL = 'https://posthog.com/docs/support/widget#identity-verification'

const VERIFIED_TEXT =
    "Verified identity — PostHog confirmed this person controls the identity on the ticket (a signed widget request, an authenticated email, or a validated Slack, Teams, or GitHub event). For a widget ticket, the check covers the signed-in account. The name and email on the ticket come from the form and aren't checked."
const UNVERIFIED_TEXT =
    "Unverified identity — this ticket was raised anonymously, so the claimed identity may not belong to this person. Confirm who you're talking to before sharing account details."
const UNKNOWN_TEXT =
    "Unknown identity — PostHog never checked who's on this ticket. This happens for tickets created before identity verification existed, or outbound tickets where the recipient hasn't replied yet. Confirm who you're talking to before sharing account details."

export function identityBadgeTooltip(verified: boolean | null): string {
    return verified ? VERIFIED_TEXT : verified === false ? UNVERIFIED_TEXT : UNKNOWN_TEXT
}
