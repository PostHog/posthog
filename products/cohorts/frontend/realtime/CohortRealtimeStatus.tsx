import { useState } from 'react'

import { IconBolt, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDialog, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { CohortHistoryBuildPhaseEnumApi, CohortRealtimeReadinessApi } from '../generated/api.schemas'
import { RealtimeCohortsUsage } from './RealtimeCohortsUsage'
import { RealtimePlanLimitsLink } from './RealtimePlanLimitsLink'
import { dailyReasonSentence, unpreparableExplanation } from './realtimeReadiness'

// Partial, so the fallback below stays reachable for a phase this bundle predates.
const PHASE_DETAIL: Partial<Record<CohortHistoryBuildPhaseEnumApi, string>> = {
    waiting: 'Waiting to start',
    scanning: 'Reading past events',
    checking: 'Checking who matches',
}

const OTHER_CHANGE_IN_FLIGHT = 'Wait for the current change to finish'

function inFlightProps(
    switching: boolean,
    switchingTo: boolean | null,
    enabled: boolean
): { loading: boolean; disabledReason: string | undefined } {
    return {
        loading: switching && switchingTo === enabled,
        disabledReason: switching && switchingTo !== enabled ? OTHER_CHANGE_IN_FLIGHT : undefined,
    }
}

const canRetry = (realtime: CohortRealtimeReadinessApi | null | undefined): boolean =>
    realtime?.state === 'needs_attention' && realtime.reason === null

type RowContent = { label: JSX.Element; tooltip: JSX.Element }

export type CohortRealtimeSwitchAction = 'turn_on' | 'turn_off'

/** The label shown beside "Flag targeting:", and the sentence its ⓘ carries. */
function rowContent(realtime: CohortRealtimeReadinessApi): RowContent | null {
    switch (realtime.state) {
        case 'ready':
            return {
                label: (
                    <span className="flex items-center gap-x-1">
                        <IconBolt className="text-base" />
                        Available
                    </span>
                ),
                tooltip: (
                    <div className="space-y-1">
                        <div>
                            This is a realtime cohort. Feature flags can target it and see membership changes within
                            about a minute. The member count and the people listed on this page still update once a day.
                        </div>
                        {realtime.ready_at && (
                            <div>
                                Ready since <TZLabel time={realtime.ready_at} />
                            </div>
                        )}
                    </div>
                ),
            }
        case 'building':
        case 'rebuilding':
            return {
                label: (
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
                ),
                tooltip: (
                    <div>
                        {realtime.state === 'rebuilding'
                            ? 'The criteria changed, so PostHog is rebuilding this cohort from past events before feature flags can target it again. This usually takes under 30 minutes.'
                            : 'PostHog is catching up on past events so feature flags can target this cohort. This usually takes under 30 minutes.'}
                    </div>
                ),
            }
        case 'needs_attention': {
            const unpreparable = unpreparableExplanation(realtime)
            if (unpreparable) {
                return {
                    label: <span className="text-secondary">Unavailable</span>,
                    tooltip: <div>{unpreparable}</div>,
                }
            }
            return {
                label: <span className="text-secondary">Unavailable</span>,
                tooltip: (
                    <div>
                        {realtime.reason === 'too_large_to_build'
                            ? "Feature flags can't target this cohort yet. The events in its criteria happen too often for PostHog to prepare it automatically. Contact support to have it prepared."
                            : 'Feature flags can\'t target this cohort yet because PostHog hasn\'t prepared it. Select "Try again" to have PostHog prepare it, and contact support if it stays unavailable.'}
                    </div>
                ),
            }
        }
        case 'off':
            if (realtime.reason === 'history_over_limit' && realtime.history_limit_days !== null) {
                return {
                    label: (
                        <span className="flex items-center gap-x-2 flex-wrap">
                            <span className="text-secondary">Off</span>
                            <RealtimePlanLimitsLink limit="history_days" location="cohort_page" />
                        </span>
                    ),
                    tooltip: (
                        <div>
                            {`Realtime is off for this cohort, so feature flags can't target it. Realtime cohorts on your plan can look back at most ${realtime.history_limit_days} days, and its criteria look back further. Shorten the time range in its criteria to turn realtime on.`}
                        </div>
                    ),
                }
            }
            if (realtime.reason) {
                return {
                    label: <span className="text-secondary">Off</span>,
                    tooltip: <div>{unpreparableExplanation(realtime)}</div>,
                }
            }
            return {
                label: <span className="text-secondary">Off</span>,
                tooltip: (
                    <div>
                        Realtime is off for this cohort, so feature flags can't target it. When you turn it on, PostHog
                        prepares the cohort from past events. This usually takes under 30 minutes.
                    </div>
                ),
            }
        case 'daily':
            return {
                label: <span className="text-secondary">Unavailable</span>,
                tooltip: (
                    <div>
                        {`Feature flags can't target this cohort. ${dailyReasonSentence(realtime) ?? "Its criteria are matched in the once-a-day calculation, which feature flags can't read."}`}
                    </div>
                ),
            }
        case 'person_properties':
            return {
                label: <span>Available</span>,
                tooltip: (
                    <div>
                        Feature flags can target this cohort. They read its person properties as they evaluate, so
                        membership is always current. The member count and the people listed on this page still update
                        once a day.
                    </div>
                ),
            }
        default:
            // Static cohorts, and any state this bundle predates: nothing to say.
            return null
    }
}

/**
 * What feature flags can do with this cohort right now, as a row beside the cohort's other facts.
 * Deliberately one row and not a banner: the daily calculation already has a banner on this page,
 * and two progress stories stacked on a save read as one thing failing twice.
 */
export function CohortRealtimeStatus({
    realtime,
    switchAction,
    switching,
    onSwitch,
}: {
    realtime: CohortRealtimeReadinessApi | null | undefined
    switchAction: CohortRealtimeSwitchAction | null
    switching: boolean
    onSwitch: (enabled: boolean) => void
}): JSX.Element | null {
    // "Try again" and "Turn off realtime" share one request, so only the clicked one shows the spinner.
    const [switchingTo, setSwitchingTo] = useState<boolean | null>(null)
    const content = realtime ? rowContent(realtime) : null
    if (!content) {
        return null
    }

    const percent = realtime?.build?.percent_complete ?? null

    return (
        <div className="flex flex-col gap-y-2" data-attr="cohort-realtime-status">
            <div className="flex items-center gap-x-2 my-0 flex-wrap">
                <strong>Flag targeting:</strong>
                <Tooltip title={content.tooltip}>
                    <IconInfo className="text-secondary text-base" />
                </Tooltip>
                {content.label}
                {switchAction === 'turn_on' && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        loading={switching}
                        onClick={() => onSwitch(true)}
                        data-attr="cohort-realtime-turn-on"
                    >
                        Turn on realtime
                    </LemonButton>
                )}
                {canRetry(realtime) && switchAction !== null && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        {...inFlightProps(switching, switchingTo, true)}
                        onClick={() => {
                            setSwitchingTo(true)
                            onSwitch(true)
                        }}
                        // pinned: data-attr, because autocapture insights find the click by it
                        data-attr="cohort-realtime-retry"
                    >
                        Try again
                    </LemonButton>
                )}
                {switchAction === 'turn_off' && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        {...inFlightProps(switching, switchingTo, false)}
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Turn off realtime for this cohort?',
                                description:
                                    realtime?.state === 'person_properties'
                                        ? "Workflows won't see membership changes for this cohort as they happen. Feature flags read its person properties directly, so they keep targeting it."
                                        : "Feature flags won't be able to target this cohort. If you turn realtime on again, PostHog prepares the cohort from past events again.",
                                primaryButton: {
                                    children: 'Turn off',
                                    status: 'danger',
                                    onClick: () => {
                                        setSwitchingTo(false)
                                        onSwitch(false)
                                    },
                                    'data-attr': 'cohort-realtime-turn-off-confirm',
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        data-attr="cohort-realtime-turn-off"
                    >
                        Turn off realtime
                    </LemonButton>
                )}
            </div>
            {switchAction !== null && <RealtimeCohortsUsage location="cohort_page" />}
            {percent !== null && (
                <LemonProgress
                    percent={percent}
                    className="max-w-80"
                    role="progressbar"
                    aria-label="Cohort preparation progress"
                    aria-valuenow={percent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                />
            )}
        </div>
    )
}
