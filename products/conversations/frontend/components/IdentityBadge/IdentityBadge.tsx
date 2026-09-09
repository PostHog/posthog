import { IconShield, IconShieldEmpty, IconShieldExclamation } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

const DOCS_URL = 'https://posthog.com/docs/support/widget#identity-verification'

const VERIFIED_TEXT =
    "Verified identity — PostHog confirmed this person controls the identity on the ticket (a signed widget request, an authenticated email, or a validated Slack, Teams, or GitHub event). You can trust who you're talking to."
const UNVERIFIED_TEXT =
    "Unverified identity — this ticket was raised anonymously, so the claimed identity may not belong to this person. Confirm who you're talking to before sharing account details."
const UNKNOWN_TEXT =
    "Unknown identity — PostHog never checked who's on this ticket. This happens for tickets created before identity verification existed, or outbound tickets where the recipient hasn't replied yet. Confirm who you're talking to before sharing account details."

interface IdentityBadgeProps {
    /** True = verified, false = assessed but not verified, null = unknown. */
    verified: boolean | null
    /** Icon-only rendering */
    iconOnly?: boolean
}

function IdentityTooltipContent({ text }: { text: string }): JSX.Element {
    return (
        <>
            {text}
            <p className="mb-0 mt-1">
                <Link
                    to={DOCS_URL}
                    target="_blank"
                    className="text-xs"
                    data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                    data-ph-capture-attribute-doclink={DOCS_URL}
                >
                    Read the docs
                </Link>
            </p>
        </>
    )
}

export function IdentityBadge({ verified, iconOnly = false }: IdentityBadgeProps): JSX.Element {
    const tooltip = verified ? VERIFIED_TEXT : verified === false ? UNVERIFIED_TEXT : UNKNOWN_TEXT
    // verified → shield+tick, unverified → shield+exclamation, unknown → empty shield
    const icon = verified ? <IconShield /> : verified === false ? <IconShieldExclamation /> : <IconShieldEmpty />
    // verified → green, unverified → amber, unknown → muted grayscale
    const iconColor = verified ? 'text-success' : verified === false ? 'text-warning' : 'text-muted-alt'
    const badgeVariant = verified ? 'success' : verified === false ? 'warning' : 'default'

    if (iconOnly) {
        return (
            <Tooltip>
                <TooltipTrigger render={<span className={iconColor} />}>{icon}</TooltipTrigger>
                <TooltipContent>
                    <IdentityTooltipContent text={tooltip} />
                </TooltipContent>
            </Tooltip>
        )
    }

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge variant={badgeVariant}>
                        {icon}
                        {verified ? 'Verified' : verified === false ? 'Unverified' : 'Unknown'}
                    </Badge>
                }
            />
            <TooltipContent>
                <IdentityTooltipContent text={tooltip} />
            </TooltipContent>
        </Tooltip>
    )
}
