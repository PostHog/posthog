import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, Link } from '@posthog/lemon-ui'
import { Button, Spinner as QuillSpinner } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'

import { cohortRealtimeReadinessLogic } from './cohortRealtimeReadinessLogic'
import { RealtimeCohortsUsage } from './RealtimeCohortsUsage'
import { RealtimePlanLimitsLink } from './RealtimePlanLimitsLink'

/** One cohort a condition set targets that feature flags can't target yet: why, and what to do about it. */
export function CohortFlagTargetingNoticeRow({ cohortId }: { cohortId: number }): JSX.Element | null {
    const logic = cohortRealtimeReadinessLogic({ cohortId })
    const { cohort, realtimeSwitchLoading } = useValues(logic)
    const { turnOnRealtime } = useActions(logic)
    const quillSurface = useQuillSurface()
    const realtime = cohort?.realtime
    if (!cohort || !realtime) {
        return null
    }

    // A new tab, because leaving the flag editor would discard its unsaved conditions.
    const name = quillSurface ? (
        <Button
            variant="link"
            size="inline"
            nativeButton={false}
            render={<LinkPrimitive to={urls.cohort(cohortId)} target="_blank" />}
        >
            {cohort.name}
        </Button>
    ) : (
        <Link to={urls.cohort(cohortId)} target="_blank">
            {cohort.name}
        </Link>
    )

    const turnOn = (): void => {
        // pinned: analytics event name and properties, because insights that count clicks read them
        posthog.capture('cohort realtime turn on clicked', { location: 'flag_editor' })
        turnOnRealtime()
    }

    switch (realtime.state) {
        case 'off':
            if (realtime.reason === 'history_over_limit' && realtime.history_limit_days !== null) {
                return (
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span>
                            Feature flags can't target {name}.{' '}
                            <span>{`Realtime cohorts on your plan can look back at most ${realtime.history_limit_days} days, and its criteria look back further. Shorten the time range in its criteria to turn realtime on.`}</span>
                        </span>
                        <RealtimePlanLimitsLink limit="history_days" location="flag_editor" />
                    </div>
                )
            }
            return (
                <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span>
                            Realtime is off for {name}, so feature flags can't target it yet. When you turn it on,
                            PostHog prepares the cohort from past events. This usually takes under 30 minutes. You can
                            save once it's ready.
                        </span>
                        {quillSurface ? (
                            <Button
                                variant="outline"
                                loading={realtimeSwitchLoading}
                                aria-label={`Turn on realtime for ${cohort.name}`}
                                onClick={turnOn}
                                data-attr="cohort-realtime-turn-on-flag-editor"
                            >
                                Turn on realtime
                            </Button>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                loading={realtimeSwitchLoading}
                                aria-label={`Turn on realtime for ${cohort.name}`}
                                onClick={turnOn}
                                data-attr="cohort-realtime-turn-on-flag-editor"
                            >
                                Turn on realtime
                            </LemonButton>
                        )}
                    </div>
                    <RealtimeCohortsUsage location="flag_editor" />
                </div>
            )
        case 'building':
        case 'rebuilding':
            return (
                <div className="flex items-start gap-2">
                    {quillSurface ? (
                        <QuillSpinner className="shrink-0 mt-0.5" />
                    ) : (
                        <Spinner size="small" className="shrink-0 mt-0.5" />
                    )}
                    {realtime.state === 'rebuilding' ? (
                        <span>
                            The criteria of {name} changed, so PostHog is preparing it again from past events. You can
                            save once it's ready.
                        </span>
                    ) : (
                        <span>
                            PostHog is preparing {name} from past events. You can save once it's ready, which usually
                            takes under 30 minutes.
                        </span>
                    )}
                </div>
            )
        case 'needs_attention':
            return realtime.reason === 'too_large_to_build' ? (
                <span>
                    Feature flags can't target {name} yet. The events in its criteria happen too often for PostHog to
                    prepare it automatically. Contact support to have it prepared.
                </span>
            ) : (
                <span>
                    Feature flags can't target {name} yet, because PostHog hasn't prepared it. Contact support if this
                    doesn't change.
                </span>
            )
        case 'daily':
            return (
                <span>
                    Feature flags can't target {name}. Its criteria are matched in the once-a-day calculation, which
                    feature flags can't read.
                </span>
            )
        default:
            return null
    }
}
