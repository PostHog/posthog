import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconHeatmap } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ProductIntentContext, addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'
import { ProductKey } from '~/types'

import { webAnalyticsLogic } from '../webAnalyticsLogic'

interface HeatmapButtonProps {
    breakdownBy: WebStatsBreakdown
    value: string
}

// Currently can only support breakdown where the value is a pathname
const VALID_BREAKDOWN_VALUES = new Set([
    WebStatsBreakdown.Page,
    WebStatsBreakdown.InitialPage,
    WebStatsBreakdown.ExitPage,
    WebStatsBreakdown.ExitClick,
    WebStatsBreakdown.FrustrationMetrics,
])

export const HeatmapButton = ({ breakdownBy, value }: HeatmapButtonProps): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { domainFilter: webAnalyticsSelectedDomain } = useValues(webAnalyticsLogic)

    // Doesn't make sense to show the button if there's no value
    if (value === '') {
        return <></>
    }

    // Currently heatmaps only support pathnames,
    // so we ignore the other breakdown types
    if (!VALID_BREAKDOWN_VALUES.has(breakdownBy)) {
        return <></>
    }

    // When there's no domain filter selected, display a disabled button with a tooltip
    if (!webAnalyticsSelectedDomain || webAnalyticsSelectedDomain === 'all') {
        return (
            <LemonButton
                disabledReason="Select a domain to view heatmaps"
                icon={<IconHeatmap />}
                type="tertiary"
                size="xsmall"
                tooltip="View heatmap for this page"
                className="no-underline"
            />
        )
    }

    // Normalize domain and path then join with a slash
    const domain = webAnalyticsSelectedDomain.endsWith('/')
        ? webAnalyticsSelectedDomain.slice(0, -1)
        : webAnalyticsSelectedDomain
    const path = value.startsWith('/') ? value.slice(1) : value
    const url = `${domain}/${path}`

    // Decide whether to use the new heatmaps UI or launch the user's website with the toolbar + heatmaps
    const to = featureFlags[FEATURE_FLAGS.HEATMAPS_UI]
        ? urls.heatmaps(`pageURL=${url}`)
        : appEditorUrl(url, { userIntent: 'heatmaps' })

    return (
        <LemonButton
            to={to}
            icon={<IconHeatmap />}
            type="tertiary"
            size="xsmall"
            tooltip="View heatmap for this page"
            className="no-underline"
            targetBlank
            onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
                void addProductIntentForCrossSell({
                    from: ProductKey.WEB_ANALYTICS,
                    to: ProductKey.HEATMAPS,
                    intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                })
            }}
        />
    )
}
