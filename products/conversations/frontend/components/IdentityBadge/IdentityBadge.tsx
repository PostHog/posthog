import { IconShield, IconWarning } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

const DOCS_URL = 'https://posthog.com/docs/support/widget#identity-verification'

const VERIFIED_TEXT = 'The identity of the person that raised this ticket has been verified by PostHog.'
const UNVERIFIED_TEXT =
    'This ticket was raised anonymously, so the claimed identity may not belong to this person. Be cautious before sharing account details.'

interface IdentityBadgeProps {
    verified: boolean
    /** Icon-only rendering */
    iconOnly?: boolean
}

export function IdentityBadge({ verified, iconOnly = false }: IdentityBadgeProps): JSX.Element {
    const tooltip = verified ? VERIFIED_TEXT : UNVERIFIED_TEXT

    if (iconOnly) {
        return (
            <Tooltip title={tooltip} docLink={DOCS_URL}>
                <span className={verified ? 'text-success' : 'text-warning'}>
                    {verified ? <IconShield /> : <IconWarning />}
                </span>
            </Tooltip>
        )
    }

    return (
        <Tooltip title={tooltip} docLink={DOCS_URL}>
            <LemonTag type={verified ? 'success' : 'warning'}>
                <span className="mr-1">{verified ? <IconShield /> : <IconWarning />}</span>
                {verified ? 'Verified' : 'Unverified'}
            </LemonTag>
        </Tooltip>
    )
}
