import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { todayAnalyticsLogic } from './todayAnalyticsLogic'

const CUSTOMIZE_PROMPT =
    'Help me customize my Analytics sidebar. Show me what is in it now, then ask me what I want to see there.'

/** The way to change the sidebar: PostHog AI builds a layout, and a customized one can go back to the default. */
export function TodayAnalyticsSidebarCustomize(): JSX.Element | null {
    const { sidebarLayout, sidebarCustomized, sidebarLoading } = useValues(todayAnalyticsLogic)
    const { resetSidebar } = useActions(todayAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // Only the PostHog AI that runs in a sandbox has the tools that save a layout.
    const canCustomize = !!featureFlags[FEATURE_FLAGS.PHAI_SANDBOX_MODE]

    if (!canCustomize && !sidebarCustomized) {
        return null
    }
    return (
        <div className="mt-2 flex flex-wrap items-center gap-1 border-t border-border pt-2">
            {canCustomize && (
                <Button
                    size="sm"
                    variant="link-muted"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.ai(undefined, CUSTOMIZE_PROMPT)} />}
                    onClick={() =>
                        // pinned: analytics event name and property. Renaming them breaks dashboards.
                        posthog.capture('analytics sidebar customize clicked', { customized: sidebarCustomized })
                    }
                    data-attr="analytics-sidebar-customize"
                >
                    <IconSparkles />
                    Customize with PostHog AI
                </Button>
            )}
            {sidebarCustomized && (
                <Button
                    size="sm"
                    variant="link-muted"
                    loading={sidebarLoading}
                    onClick={() => resetSidebar(sidebarLayout)}
                    data-attr="analytics-sidebar-reset"
                >
                    Reset to default
                </Button>
            )}
        </div>
    )
}
