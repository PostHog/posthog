import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { ProductTab } from './common'
import { webAnalyticsFilterPresetsLogic } from './webAnalyticsFilterPresetsLogic'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export function WebAnalyticsSavePresetNudge(): JSX.Element | null {
    const { productTab, hasNonDefaultFilters, appliedPresetShortId } = useValues(webAnalyticsLogic)
    const { openSaveModal } = useActions(webAnalyticsFilterPresetsLogic)

    if (productTab !== ProductTab.ANALYTICS || !hasNonDefaultFilters || appliedPresetShortId) {
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
            Save these filters as a preset so you can come back to them in one click.
        </LemonBanner>
    )
}
