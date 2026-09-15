import { IconBolt, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { CohortHistoryBuildPhaseEnumApi, CohortRealtimeReadinessApi } from '../generated/api.schemas'

const PHASE_DETAIL: Record<CohortHistoryBuildPhaseEnumApi, string> = {
    waiting: 'Waiting to start',
    scanning: 'Reading past events',
    checking: 'Checking who matches',
}

/**
 * What feature flags can do with this cohort right now, as a row beside the cohort's other facts.
 * Deliberately one row and not a banner: the daily calculation already has a banner on this page,
 * and two progress stories stacked on a save read as one thing failing twice.
 */
export function CohortRealtimeStatus({
    realtime,
}: {
    realtime: CohortRealtimeReadinessApi | null | undefined
}): JSX.Element | null {
    if (!realtime) {
        return null
    }

    let value: JSX.Element
    let explanation: JSX.Element
    switch (realtime.state) {
        case 'ready':
            value = (
                <span className="flex items-center gap-x-1">
                    <IconBolt className="text-base" />
                    Realtime
                </span>
            )
            explanation = (
                <div className="space-y-1">
                    <div>
                        Feature flags can target this cohort and see membership changes within about a minute. The
                        member count and the people listed on this page still update once a day.
                    </div>
                    {realtime.ready_at && (
                        <div>
                            Ready since <TZLabel time={realtime.ready_at} />
                        </div>
                    )}
                </div>
            )
            break
        case 'building':
        case 'rebuilding':
            value = (
                <span className="flex items-center gap-x-2 flex-wrap">
                    <span className="flex items-center gap-x-2">
                        <Spinner size="small" />
                        Preparing
                    </span>
                    {realtime.build && (
                        <span className="text-secondary flex gap-x-1">
                            <span>{PHASE_DETAIL[realtime.build.phase] ?? 'In progress'}</span>
                            {realtime.build.updated_at && (
                                <>
                                    <span>·</span>
                                    <span>Updated</span>
                                    <TZLabel time={realtime.build.updated_at} />
                                </>
                            )}
                        </span>
                    )}
                </span>
            )
            explanation = (
                <div>
                    {realtime.state === 'rebuilding'
                        ? 'The criteria changed, so PostHog is rebuilding this cohort from past events before feature flags can target it again. This usually takes under 30 minutes.'
                        : 'PostHog is catching up on past events so feature flags can target this cohort. This usually takes under 30 minutes.'}
                </div>
            )
            break
        case 'needs_attention':
            value = <span className="text-secondary">Not available yet</span>
            explanation = (
                <div>
                    Feature flags can't target this cohort yet because PostHog hasn't prepared it. Contact support if
                    this doesn't change.
                </div>
            )
            break
        default:
            // Daily and static cohorts, and any state this bundle predates: nothing new to say.
            return null
    }

    const percent = realtime.build?.percent_complete ?? null

    return (
        <div className="flex flex-col gap-y-2" data-attr="cohort-realtime-status">
            <div className="flex items-center gap-x-2 my-0 flex-wrap">
                <strong>Feature flags:</strong>
                <Tooltip title={explanation}>
                    <IconInfo className="text-secondary text-base" />
                </Tooltip>
                {value}
            </div>
            {percent !== null && <LemonProgress percent={percent} className="max-w-80" />}
        </div>
    )
}
