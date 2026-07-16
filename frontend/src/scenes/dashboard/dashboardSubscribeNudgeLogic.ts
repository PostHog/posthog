import { BreakPointFunction, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { dashboardsSubscribeNudgeCreate } from '@posthog/products-dashboards/frontend/generated/api'
import type { DashboardSubscribeNudgeResponseApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import {
    dashboardNudgeScopeKey,
    dashboardSubscribeNudgeStoreLogic,
    freshTimestamps,
} from 'scenes/dashboard/dashboardSubscribeNudgeStoreLogic'
import { showDashboardSubscribeNudgeToast } from 'scenes/dashboard/DashboardSubscribeNudgeToast'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, DashboardPlacement } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { isFreeTierCreateAtLimit } from 'products/subscriptions/frontend/components/Subscriptions/views/EditSubscription'
import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import type { dashboardSubscribeNudgeLogicType } from './dashboardSubscribeNudgeLogicType'

export const DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD = 3

export interface DashboardSubscribeNudgeLogicProps {
    dashboardId: number
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
            userLogic,
            ['hasAvailableFeature'],
            dashboardSubscribeNudgeStoreLogic({ scope: dashboardNudgeScopeKey() }),
            ['viewLog', 'suppressedDashboardIds', 'notifiedDashboardIds'],
        ],
        actions: [
            dashboardLogic({ id: props.dashboardId }),
            ['reportDashboardViewed'],
            dashboardSubscribeNudgeStoreLogic({ scope: dashboardNudgeScopeKey() }),
            ['recordDashboardView', 'suppressDashboardNudge', 'markDashboardNotified'],
        ],
    })),
    loaders(({ props }) => ({
        // Whether this dashboard already has a subscription. null = not checked yet. Only fetched
        // once every free, local check has passed (`isCandidate`: repeat views, not already
        // nudged/dismissed, subscribable dashboard) — most dashboard views make no request at all.
        // `load` prefix + initKea's ERROR_FILTER_ALLOW_LIST keep a failed background check from
        // toasting at a user who never asked for anything.
        hasExistingSubscription: [
            null as boolean | null,
            {
                loadExistingSubscription: async (_?: unknown, breakpoint?: BreakPointFunction) => {
                    // If a subscriptionsLogic for this dashboard is already mounted (e.g. the
                    // subscriptions modal was opened), reuse its data instead of refetching.
                    const mounted = subscriptionsLogic.findMounted({ dashboardId: props.dashboardId })
                    if (mounted && !mounted.values.subscriptionsLoading) {
                        return mounted.values.subscriptions.length > 0
                    }
                    // limit=1 keeps the payload tiny; `count` reflects the dashboard's full total.
                    const response = await subscriptionsList(String(getCurrentTeamId()), {
                        dashboard: props.dashboardId,
                        limit: 1,
                    })
                    breakpoint?.()
                    return (response.count ?? 0) > 0
                },
            },
        ],
        // Team-wide subscription count, fetched only for free-tier candidates: those orgs can
        // create subscriptions until SubscriptionFreeTierLimit.COUNT, and nudging someone already
        // at the limit would push them straight into the create-form paywall.
        teamSubscriptionCount: [
            null as number | null,
            {
                loadTeamSubscriptionCount: async (_?: unknown, breakpoint?: BreakPointFunction) => {
                    // limit=1 keeps the payload tiny; `count` reflects the team's full total.
                    const response = await subscriptionsList(String(getCurrentTeamId()), { limit: 1 })
                    breakpoint?.()
                    return response.count ?? 0
                },
            },
        ],
        // Asks the backend to deliver the in-app nudge notification. The server dedupes per
        // (user, dashboard) and reports whether a notification was actually created.
        nudgeNotification: [
            null as DashboardSubscribeNudgeResponseApi | null,
            {
                sendNudgeNotification: async (_?: unknown, breakpoint?: BreakPointFunction) => {
                    const response = await dashboardsSubscribeNudgeCreate(String(getCurrentTeamId()), props.dashboardId)
                    breakpoint?.()
                    return response
                },
            },
        ],
    })),
    selectors({
        viewCount7d: [
            (s) => [s.viewLog, (_, props) => props.dashboardId],
            (viewLog, dashboardId): number => freshTimestamps(viewLog[dashboardId] ?? [], Date.now()).length,
        ],
        isPastViewThreshold: [
            (s) => [s.viewCount7d],
            (viewCount7d): boolean => viewCount7d >= DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
        ],
        isSuppressed: [
            (s) => [s.suppressedDashboardIds, (_, props) => props.dashboardId],
            (suppressedDashboardIds, dashboardId): boolean => suppressedDashboardIds.includes(dashboardId),
        ],
        isNotified: [
            (s) => [s.notifiedDashboardIds, (_, props) => props.dashboardId],
            (notifiedDashboardIds, dashboardId): boolean => notifiedDashboardIds.includes(dashboardId),
        ],
        // Excludes shared/public/embedded placements — the nudge only makes sense where "set up a
        // subscription" is an action the viewer can actually take. Free-tier orgs are NOT excluded
        // here: they can create subscriptions up to SubscriptionFreeTierLimit.COUNT, so their gate
        // is the count check in `isWithinSubscriptionLimit` instead.
        isDashboardEligible: [
            (s) => [s.dashboard, s.canEditDashboard, s.placement],
            (dashboard, canEditDashboard, placement): boolean =>
                !!dashboard && canEditDashboard && placement === DashboardPlacement.Dashboard,
        ],
        hasSubscriptionsFeature: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS),
        ],
        // Cheap half of eligibility: needs no API data, so the existing-subscription fetch only
        // happens for dashboards that pass this first.
        isCandidate: [
            (s) => [s.isPastViewThreshold, s.isSuppressed, s.isNotified, s.isDashboardEligible],
            (isPastViewThreshold, isSuppressed, isNotified, isDashboardEligible): boolean =>
                isPastViewThreshold && !isSuppressed && !isNotified && isDashboardEligible,
        ],
        // Paid orgs are never limited. Free-tier orgs must have room under the free-tier cap —
        // and unlike EditSubscription (where a null count fails open because the user explicitly
        // asked and the backend is the hard gate), a proactive nudge fails closed on an unknown
        // count: don't advertise an action we can't confirm they can complete.
        isWithinSubscriptionLimit: [
            (s) => [s.hasSubscriptionsFeature, s.teamSubscriptionCount],
            (hasSubscriptionsFeature, teamSubscriptionCount): boolean =>
                hasSubscriptionsFeature ||
                (teamSubscriptionCount !== null && !isFreeTierCreateAtLimit(teamSubscriptionCount)),
        ],
        isEligible: [
            (s) => [s.isCandidate, s.hasExistingSubscription, s.isWithinSubscriptionLimit],
            (isCandidate, hasExistingSubscription, isWithinSubscriptionLimit): boolean =>
                isCandidate && hasExistingSubscription === false && isWithinSubscriptionLimit,
        ],
        // CRITICAL: `featureFlags[...]` is a proxy access that reports the flag's exposure event the
        // first time it's read. Only touch it once `isEligible` is true, so the experiment's exposure
        // ($feature_flag_called) fires only for the population that could actually receive the nudge.
        flagVariant: [
            (s) => [s.isEligible, s.featureFlags],
            (isEligible, featureFlags): string | boolean | undefined =>
                isEligible ? featureFlags[FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE] : undefined,
        ],
        showNudge: [(s) => [s.flagVariant], (flagVariant): boolean => flagVariant === 'test'],
    }),
    listeners(({ actions, values, props }) => ({
        reportDashboardViewed: () => {
            actions.recordDashboardView(props.dashboardId)
        },
        recordDashboardView: ({ dashboardId }) => {
            if (dashboardId !== props.dashboardId || !values.isCandidate) {
                return
            }
            if (values.hasExistingSubscription === null && !values.hasExistingSubscriptionLoading) {
                actions.loadExistingSubscription()
            }
            if (
                !values.hasSubscriptionsFeature &&
                values.teamSubscriptionCount === null &&
                !values.teamSubscriptionCountLoading
            ) {
                actions.loadTeamSubscriptionCount()
            }
        },
        loadExistingSubscriptionSuccess: ({ hasExistingSubscription }) => {
            if (hasExistingSubscription) {
                // The viewer clearly knows the feature — permanently stop nudging (and rechecking)
                // this dashboard, even if the subscription is later deleted.
                actions.suppressDashboardNudge(props.dashboardId)
            }
        },
        loadExistingSubscriptionFailure: ({ error, errorObject }) => {
            // Distinguishes a broken eligibility check from genuine ineligibility in the experiment readout.
            posthog.capture('dashboard subscribe nudge check failed', {
                dashboard_id: props.dashboardId,
                step: 'check',
                error_name: errorObject?.name,
                error_status: errorObject?.status,
                error_message: error,
            })
        },
        loadTeamSubscriptionCountFailure: ({ error, errorObject }) => {
            // A failed count check silently excludes a free-tier user (fail closed) — capture it so
            // the readout can tell that apart from genuinely being at the limit.
            posthog.capture('dashboard subscribe nudge check failed', {
                dashboard_id: props.dashboardId,
                step: 'limit',
                error_name: errorObject?.name,
                error_status: errorObject?.status,
                error_message: error,
            })
        },
        sendNudgeNotificationSuccess: ({ nudgeNotification }) => {
            if (!nudgeNotification?.created) {
                // Nothing was delivered (server dedupe-skip, notifications unavailable, or user
                // opt-out) — don't burn the client marker; a later qualifying visit retries and the
                // server sentinel still collapses races.
                return
            }
            // Delivered — never request again from this browser.
            actions.markDashboardNotified(props.dashboardId)
            posthog.capture('dashboard subscribe nudge shown', {
                dashboard_id: props.dashboardId,
                view_count_7d: values.viewCount7d,
            })
            showDashboardSubscribeNudgeToast(props.dashboardId, values.dashboard?.name, values.viewCount7d)
        },
        sendNudgeNotificationFailure: ({ error, errorObject }) => {
            // Not marked notified: the next qualifying visit retries.
            posthog.capture('dashboard subscribe nudge check failed', {
                dashboard_id: props.dashboardId,
                step: 'notify',
                error_name: errorObject?.name,
                error_status: errorObject?.status,
                error_message: error,
            })
        },
    })),
    subscriptions(({ actions, values, cache }) => ({
        // The nudge is requested off the fully-gated state itself (eligibility + test variant),
        // so it also fires when feature flags resolve after the subscription check completed.
        showNudge: (showNudge: boolean) => {
            if (showNudge && !cache.nudgeRequested && !values.nudgeNotificationLoading) {
                cache.nudgeRequested = true
                actions.sendNudgeNotification()
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // Covers dashboards already past the threshold from earlier sessions; new views route
        // through the recordDashboardView listener instead.
        if (!values.isCandidate) {
            return
        }
        if (values.hasExistingSubscription === null) {
            actions.loadExistingSubscription()
        }
        if (!values.hasSubscriptionsFeature && values.teamSubscriptionCount === null) {
            actions.loadTeamSubscriptionCount()
        }
    }),
])
