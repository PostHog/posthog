import { IconShield, IconShieldEmpty, IconShieldExclamation } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IDENTITY_DOCS_URL, identityBadgeTooltip } from './identityBadgeText'

interface IdentityBadgeProps {
    /** True = verified, false = assessed but not verified, null = unknown. */
    verified: boolean | null
    /** Icon-only rendering */
    iconOnly?: boolean
}

export function IdentityBadge({ verified, iconOnly = false }: IdentityBadgeProps): JSX.Element {
    const tooltip = identityBadgeTooltip(verified)
    // verified → shield+tick, unverified → shield+exclamation, unknown → empty shield
    const icon = verified ? <IconShield /> : verified === false ? <IconShieldExclamation /> : <IconShieldEmpty />
    // verified → green, unverified → amber, unknown → muted grayscale
    const iconColor = verified ? 'text-success' : verified === false ? 'text-warning' : 'text-muted-alt'
    const tagType = verified ? 'success' : verified === false ? 'warning' : 'muted'

    if (iconOnly) {
        return (
            <Tooltip title={tooltip} docLink={IDENTITY_DOCS_URL}>
                <span className={iconColor}>{icon}</span>
            </Tooltip>
        )
    }

    return (
        <Tooltip title={tooltip} docLink={IDENTITY_DOCS_URL}>
            <LemonTag type={tagType}>
                <span className="mr-1">{icon}</span>
                {verified ? 'Verified' : verified === false ? 'Unverified' : 'Unknown'}
            </LemonTag>
        </Tooltip>
    )
}
