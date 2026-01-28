import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import { webAnalyticsFilterLogic } from '../webAnalyticsFilterLogic'
import { webAnalyticsLogic } from '../webAnalyticsLogic'

interface OpenURLButtonProps {
    breakdownBy: WebStatsBreakdown
    value: string
}

const VALID_BREAKDOWN_VALUES = new Set([
    WebStatsBreakdown.Page,
    WebStatsBreakdown.InitialPage,
    WebStatsBreakdown.ExitPage,
    WebStatsBreakdown.ExitClick,
    WebStatsBreakdown.FrustrationMetrics,
])

export const OpenURLButton = ({ breakdownBy, value }: OpenURLButtonProps): JSX.Element => {
    const { domainFilter } = useValues(webAnalyticsLogic)
    const { authorizedDomains } = useValues(webAnalyticsFilterLogic)

    if (!value || !VALID_BREAKDOWN_VALUES.has(breakdownBy)) {
        return <></>
    }

    // For ExitClick, the value is already a full URL
    if (breakdownBy === WebStatsBreakdown.ExitClick) {
        const href = value.startsWith('http') ? value : `https://${value}`
        return (
            <LemonButton
                to={href}
                icon={<IconExternal />}
                type="tertiary"
                size="xsmall"
                tooltip="Open URL"
                className="no-underline"
                targetBlank
                hideExternalLinkIcon={true}
                onClick={(e: React.MouseEvent) => {
                    e.stopPropagation()
                }}
            />
        )
    }

    // For path-based breakdowns, determine the domain to use
    let selectedDomain: string | null = null

    if (domainFilter && domainFilter !== 'all') {
        selectedDomain = domainFilter
    } else if (authorizedDomains.length === 1) {
        // Auto-select if there's only one authorized domain
        selectedDomain = authorizedDomains[0]
    }

    if (!selectedDomain) {
        return (
            <LemonButton
                disabledReason="Select a domain to open this URL"
                icon={<IconExternal />}
                type="tertiary"
                size="xsmall"
                tooltip="Open URL"
                className="no-underline"
            />
        )
    }

    // Remove protocol if present, then reconstruct
    const domain = selectedDomain.replace(/^https?:\/\//, '').replace(/\/$/, '')
    const path = value.startsWith('/') ? value.slice(1) : value
    const href = `https://${domain}/${path}`

    return (
        <LemonButton
            to={href}
            icon={<IconExternal />}
            type="tertiary"
            size="xsmall"
            tooltip="Open URL"
            className="no-underline"
            targetBlank
            hideExternalLinkIcon={true}
            onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
            }}
        />
    )
}
