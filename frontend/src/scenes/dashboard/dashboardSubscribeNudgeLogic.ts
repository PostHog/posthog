import {
    BreakPointFunction,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardViewLogLogic, freshTimestamps } from 'scenes/dashboard/dashboardViewLogLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, DashboardPlacement, SubscriptionType } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscription } from 'products/subscriptions/frontend/components/Subscriptions/utils'
import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import type { dashboardSubscribeNudgeLogicType } from './dashboardSubscribeNudgeLogicType'

export const DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD = 3

export function dashboardSubscribeNudgeDismissKey(dashboardId: number): string {
    return `dashboard-subscribe-nudge-${dashboardId}`
}

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
            ['dashboard', 'canEditDashboard', 'placement', 'showSubscriptions'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            dashboardViewLogLogic,
            ['viewLog', 'suppressedDashboardIds'],
            lemonBannerLogic({ dismissKey: dashboardSubscribeNudgeDismissKey(props.dashboardId) }),
            ['isDismissed'],
        ],
        actions: [
            dashboardLogic({ id: props.dashboardId }),
            ['reportDashboardViewed', 'setSubscriptionMode'],
            dashboardViewLogLogic,
            ['recordDashboardView', 'suppressDashboardNudge'],
            lemonBannerLogic({ dismissKey: dashboardSubscribeNudgeDismissKey(props.dashboardId) }),
            ['dismiss'],
        ],
    })),
    actions({
        subscribeClicked: true,
        setSubscriptionPrefill: (prefill: Partial<SubscriptionType> | null) => ({ prefill }),
    }),
    loaders(({ props }) => ({
        // Whether this dashboard already has a subscription. null = not checked yet. Fetched only for
        // candidate dashboards, so the vast majority of dashboard views trigger no request at all.
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
    })),
    reducers({
        /** Field defaults handed to the subscription form when the nudge CTA opens it. */
        subscriptionPrefill: [
            null as Partial<SubscriptionType> | null,
            {
                setSubscriptionPrefill: (_, { prefill }) => prefill,
                // Cleared as soon as the route leaves the 'new' form (modal close, or cancel back to the
                // subscriptions list) so a stale prefill can't leak into a later, unrelated "new subscription".
                setSubscriptionMode: (state, { enabled, id }) => (enabled && id === 'new' ? state : null),
            },
        ],
    }),
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
        // Excludes shared/public/embedded placements and paywalled orgs — the nudge only makes sense
        // where "set up a subscription" is an action the viewer can actually take.
        isDashboardEligible: [
            (s) => [s.dashboard, s.canEditDashboard, s.placement, s.hasAvailableFeature],
            (dashboard, canEditDashboard, placement, hasAvailableFeature): boolean =>
                !!dashboard &&
                canEditDashboard &&
                placement === DashboardPlacement.Dashboard &&
                hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS),
        ],
        // Cheap half of eligibility: needs no API data, so the existing-subscription fetch only
        // happens for dashboards that pass this first.
        isCandidate: [
            (s) => [s.isPastViewThreshold, s.isDismissed, s.isSuppressed, s.isDashboardEligible],
            (isPastViewThreshold, isDismissed, isSuppressed, isDashboardEligible): boolean =>
                isPastViewThreshold && !isDismissed && !isSuppressed && isDashboardEligible,
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
    listeners(({ actions, values, props, selectors }) => ({
        reportDashboardViewed: () => {
            actions.recordDashboardView(props.dashboardId)
        },
        recordDashboardView: ({ dashboardId }) => {
            if (
                dashboardId === props.dashboardId &&
                values.isCandidate &&
                values.hasExistingSubscription === null &&
                !values.hasExistingSubscriptionLoading
            ) {
                actions.loadExistingSubscription()
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
                error_name: errorObject?.name,
                error_status: errorObject?.status,
                error_message: error,
            })
        },
        setSubscriptionMode: ({ enabled }, _breakpoint, _action, previousState) => {
            // The subscriptions modal closed on this same mounted scene: the user may have just
            // created a subscription via the nudge, so re-check instead of trusting the stale
            // "no subscription" answer (which would resurface the banner). previousState tells a
            // real modal close apart from the setSubscriptionMode(false) every /dashboard/:id
            // navigation dispatches — only the former warrants a re-fetch.
            const wasOpen = selectors.showSubscriptions(previousState)
            if (!enabled && wasOpen && values.hasExistingSubscription === false) {
                actions.loadExistingSubscription()
            }
        },
        dismiss: () => {
            posthog.capture('dashboard subscribe nudge dismissed', {
                dashboard_id: props.dashboardId,
                view_count_7d: values.viewCount7d,
            })
        },
        subscribeClicked: () => {
            posthog.capture('dashboard subscribe nudge clicked', {
                dashboard_id: props.dashboardId,
                view_count_7d: values.viewCount7d,
                prefilled: !!values.user?.email,
            })
            // Frequency (weekly), day (Monday), time (morning), and destination (email) already match
            // the subscription form's own defaults — only the name and recipient need prefilling.
            actions.setSubscriptionPrefill({
                title: `${values.dashboard?.name || 'Dashboard'} weekly digest`,
                ...(values.user?.email ? { target_value: values.user.email } : {}),
            })
            router.actions.push(urlForSubscription('new', { dashboardId: props.dashboardId }))
        },
    })),
    subscriptions(({ values, props, cache }) => ({
        // The impression is captured off the rendered state itself (not the subscription-check
        // result), so it also fires when feature flags resolve after the check completed.
        showNudge: (showNudge: boolean) => {
            if (showNudge && !cache.shownCaptured) {
                cache.shownCaptured = true
                posthog.capture('dashboard subscribe nudge shown', {
                    dashboard_id: props.dashboardId,
                    view_count_7d: values.viewCount7d,
                })
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // Covers dashboards already past the threshold from earlier sessions; new views route
        // through the recordDashboardView listener instead.
        if (values.isCandidate && values.hasExistingSubscription === null) {
            actions.loadExistingSubscription()
        }
    }),
])
