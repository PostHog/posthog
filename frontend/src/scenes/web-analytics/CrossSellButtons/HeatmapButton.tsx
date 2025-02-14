import { LemonButton, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import {
    appEditorUrl,
    authorizedUrlListLogic,
    AuthorizedUrlListType,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconHeatmap } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { WebStatsBreakdown } from '~/queries/schema'
import { ProductKey } from '~/types'

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
])

export const HeatmapButton = ({ breakdownBy, value }: HeatmapButtonProps): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { authorizedUrls } = useValues(
        authorizedUrlListLogic({
            actionId: null,
            experimentId: null,
            type: AuthorizedUrlListType.TOOLBAR_URLS, // Heatmap is a toolbar feature, requires authorized URLs
        })
    )

    // Doesn't make sense to show the button if there's no value
    if (value === '') {
        return <></>
    }

    // Currently heatmaps only support pathnames,
    // so we ignore the other breakdown types
    if (!VALID_BREAKDOWN_VALUES.has(breakdownBy)) {
        return <></>
    }

    // KLUDGE: We don't have any idea what domain the pathname belongs to, but we *need* the domain
    // to make it work on heatmaps. For now, let's just assume it's the main authorized domain,
    // and they'll notice the error. We're working on adding domain filtering to Web Analytics,
    // once that's live we can come back and fix this
    const domain = authorizedUrls[0]
    if (!domain) {
        return (
            <LemonButton
                icon={<IconHeatmap />}
                type="tertiary"
                size="xsmall"
                disabledReason={
                    <span>
                        No authorized URLs found. Authorize them first in{' '}
                        <Link target="blank" to={urls.toolbarLaunch()}>
                            the toolbar settings
                        </Link>
                        .
                    </span>
                }
                onClick={(e) => e.stopPropagation()}
            />
        )
    }

    // Replace double slashes with single slashes in case domain has a trailing slash, and value has a leading slash
    const url = `${domain}${value}`.replace(/\/\//, '/')

    // Decide whether to use the new heatmaps UI or launch the user's website with the toolbar + heatmaps
    const to = featureFlags[FEATURE_FLAGS.HEATMAPS_UI]
        ? urls.heatmaps(`pageURL=${url}`)
        : appEditorUrl(url, {
              userIntent: 'heatmaps',
          })

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
