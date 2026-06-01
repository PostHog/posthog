import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { type OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { InfinityValue } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

// Only surface the "ask Max why" affordance when a metric moved enough to be worth investigating.
const NOTABLE_CHANGE_THRESHOLD_PCT = 25

/**
 * Inline "ask Max why" button shown on an overview metric whose period-over-period change is notable.
 * Opens Max with a metric-specific prompt; the scene-level investigate_web_analytics registration supplies
 * the current filters as context. Renders nothing when the flag is off or the change isn't notable.
 */
export function WebAnalyticsOverviewItemAction({ item }: { item: OverviewItem }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const change = item.changeFromPreviousPct
    if (
        !featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_AI_SUMMARY] ||
        change == null ||
        Math.abs(change) < NOTABLE_CHANGE_THRESHOLD_PCT ||
        // OverviewGrid treats this sentinel as "previous period was 0" — no meaningful % change.
        Math.abs(change) >= InfinityValue.INFINITY_VALUE
    ) {
        return null
    }

    const label = labelFromKey(item.key).toLowerCase()
    const direction = change > 0 ? 'increase' : 'drop'
    const prompt = `!Why did ${label} ${direction} ${Math.abs(Math.round(change))}% in the current view?`

    return (
        <AIConsentPopoverWrapper onApprove={() => openSidePanel(SidePanelTab.Max, prompt)}>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconSparkles />}
                noPadding
                tooltip="Ask PostHog AI why this changed"
                aria-label={`Ask PostHog AI why ${label} changed`}
                onClick={() => openSidePanel(SidePanelTab.Max, prompt)}
                data-attr="web-analytics-overview-ask-max"
            />
        </AIConsentPopoverWrapper>
    )
}
