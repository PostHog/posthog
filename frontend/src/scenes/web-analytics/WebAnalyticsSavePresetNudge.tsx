import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ProductTab } from './common'
import { webAnalyticsFilterPresetsLogic } from './webAnalyticsFilterPresetsLogic'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export function WebAnalyticsSavePresetNudge(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { productTab, hasNonDefaultFilters, appliedPresetShortId } = useValues(webAnalyticsLogic)
    const { openSaveModal } = useActions(webAnalyticsFilterPresetsLogic)

    if (
        !featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] ||
        productTab !== ProductTab.ANALYTICS ||
        !hasNonDefaultFilters ||
        appliedPresetShortId
    ) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            dismissKey="web-analytics-save-preset-nudge"
            action={{
                children: 'Save as preset',
                onClick: () => {
                    posthog.capture('web analytics save preset nudge clicked')
                    openSaveModal()
                },
            }}
        >
            Save these filters as a preset. Saved presets are refreshed in the background, so they load faster when you
            come back to them.
        </LemonBanner>
    )
}
