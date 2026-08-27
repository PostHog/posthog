import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import type { FeatureFlagRolloutSummaryApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagsTab } from './featureFlagsLogic'

// The status endpoint returns reasons without terminating punctuation, and the banner reads them
// next to sentences written here.
function asSentence(reason: string): string {
    const trimmed = reason.trim()
    if (!trimmed || /[.!?]$/.test(trimmed)) {
        return trimmed
    }
    return `${trimmed}.`
}

// Rollout is supporting detail, not a second verdict on staleness. When the flag has targeting
// conditions, `max_rollout_percentage` is a share of the targeted segment and not of all users,
// so the sentence must say so.
function rolloutSentence(rollout: FeatureFlagRolloutSummaryApi | undefined): string | null {
    if (!rollout) {
        return null
    }
    if (rollout.effectively_full_rollout) {
        return 'A release condition rolls out to everyone with no targeting, so this flag resolves to one result for all users.'
    }
    if (rollout.has_targeting_conditions && rollout.max_rollout_percentage !== null) {
        const percentage = rollout.max_rollout_percentage
        return `Its highest rollout is ${percentage}% within a targeted condition, not ${percentage}% of all users.`
    }
    return null
}

export function FeatureFlagStaleBanner(): JSX.Element | null {
    const { showStaleFlagBanner, flagStatus, hasExperiment, dependentFlags } = useValues(featureFlagLogic)
    const { setSelectedTab } = useActions(featureFlagLogic)

    if (!showStaleFlagBanner || !flagStatus) {
        return null
    }

    const rollout = rolloutSentence(flagStatus.rollout)

    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'View usage',
                'data-attr': 'feature-flag-stale-banner-view-usage',
                onClick: () => {
                    posthog.capture('feature flag stale banner view usage clicked')
                    setSelectedTab(FeatureFlagsTab.USAGE)
                },
            }}
        >
            <div className="flex flex-col gap-1">
                <strong>This flag may no longer be needed</strong>
                <span>
                    {asSentence(flagStatus.reason)}
                    {rollout ? ` ${rollout}` : ''}
                </span>
                {hasExperiment && <span>This flag is linked to an experiment.</span>}
                {dependentFlags.length > 0 && <span>Other flags depend on this flag.</span>}
                <span>Review usage and code references before disabling or archiving this flag.</span>
            </div>
        </LemonBanner>
    )
}
