import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { DashboardPlacement } from '~/types'

import type { dashboardSubscribeNudgeLogicType } from './dashboardSubscribeNudgeLogicType'

export const DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD = 3
export const DASHBOARD_SUBSCRIBE_NUDGE_WINDOW_MS = 7 * 24 * 60 * 60 * 1000

export interface DashboardSubscribeNudgeLogicProps {
    dashboardId: number
}

// Keeps only the timestamps still inside the trailing 7-day window.
function pruneOldViews(timestamps: number[], now: number): number[] {
    const cutoff = now - DASHBOARD_SUBSCRIBE_NUDGE_WINDOW_MS
    return timestamps.filter((timestamp) => timestamp > cutoff)
}

export const dashboardSubscribeNudgeLogic = kea<dashboardSubscribeNudgeLogicType>([
    path((key) => ['scenes', 'dashboard', 'dashboardSubscribeNudgeLogic', key]),
    props({} as DashboardSubscribeNudgeLogicProps),
    key((props) => props.dashboardId),
    connect((props: DashboardSubscribeNudgeLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            dashboardLogic({ id: props.dashboardId }),
            ['dashboard', 'canEditDashboard', 'placement'],
        ],
        actions: [dashboardLogic({ id: props.dashboardId }), ['reportDashboardViewed']],
    })),
    actions({
        recordView: true,
        dismiss: true,
        // Whether this dashboard already has a subscription is resolved asynchronously (and only
        // fetched for candidates past the view threshold — see DashboardSubscribeNudge.tsx), so it's
        // reported in rather than derived here. null = not yet known.
        setHasExistingSubscription: (hasExistingSubscription: boolean) => ({ hasExistingSubscription }),
    }),
    reducers({
        viewTimestamps: [
            [] as number[],
            { persist: true },
            {
                recordView: (state) => pruneOldViews([...state, Date.now()], Date.now()),
            },
        ],
        dismissed: [
            false,
            { persist: true },
            {
                dismiss: () => true,
            },
        ],
        hasExistingSubscription: [
            null as boolean | null,
            {
                setHasExistingSubscription: (_, { hasExistingSubscription }) => hasExistingSubscription,
            },
        ],
    }),
    selectors({
        viewCount7d: [
            (s) => [s.viewTimestamps],
            (viewTimestamps): number => pruneOldViews(viewTimestamps, Date.now()).length,
        ],
        isPastViewThreshold: [
            (s) => [s.viewCount7d],
            (viewCount7d): boolean => viewCount7d >= DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
        ],
        // Excludes shared/public/embedded placements — the nudge only makes sense on the dashboard
        // owner's own saved-dashboard view, where "set up a subscription" is an action they can take.
        isDashboardEligible: [
            (s) => [s.dashboard, s.canEditDashboard, s.placement],
            (dashboard, canEditDashboard, placement): boolean =>
                !!dashboard && canEditDashboard && placement === DashboardPlacement.Dashboard,
        ],
        // Cheap half of eligibility: doesn't require knowing the dashboard's subscription count, so
        // components can check this before deciding whether it's worth loading subscriptions at all.
        isCandidate: [
            (s) => [s.isPastViewThreshold, s.dismissed, s.isDashboardEligible],
            (isPastViewThreshold, dismissed, isDashboardEligible): boolean =>
                isPastViewThreshold && !dismissed && isDashboardEligible,
        ],
        isEligible: [
            (s) => [s.isCandidate, s.hasExistingSubscription],
            (isCandidate, hasExistingSubscription): boolean => isCandidate && hasExistingSubscription === false,
        ],
        // CRITICAL: `featureFlags[...]` is a proxy access that reports the flag's exposure event the
        // first time it's read. Only touch it once `isEligible` is true, so the experiment's exposure
        // ($feature_flag_called) fires only for the population that could actually see the banner.
        flagVariant: [
            (s) => [s.isEligible, s.featureFlags],
            (isEligible, featureFlags): string | boolean | undefined =>
                isEligible ? featureFlags[FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE] : undefined,
        ],
        showNudge: [(s) => [s.flagVariant], (flagVariant): boolean => flagVariant === 'test'],
    }),
    listeners(({ actions, values, props, cache }) => ({
        reportDashboardViewed: () => {
            actions.recordView()
        },
        dismiss: () => {
            posthog.capture('dashboard subscribe nudge dismissed', {
                dashboard_id: props.dashboardId,
                view_count_7d: values.viewCount7d,
            })
        },
        setHasExistingSubscription: () => {
            if (values.showNudge && !cache.shownCaptured) {
                cache.shownCaptured = true
                posthog.capture('dashboard subscribe nudge shown', {
                    dashboard_id: props.dashboardId,
                    view_count_7d: values.viewCount7d,
                })
            }
        },
    })),
])
