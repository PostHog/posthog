import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import {
    subscriptionsDeliveriesList,
    subscriptionsDeliveriesRetrieve,
    subscriptionsPartialUpdate,
    subscriptionsPreviewCreate,
    subscriptionsRetrieve,
    subscriptionsTestDeliveryCreate,
} from '@posthog/products-subscriptions/frontend/generated/api'
import type {
    PaginatedSubscriptionDeliveryListApi,
    SubscriptionApi,
    SubscriptionApiAiQueryPlan,
    SubscriptionDeliveryApi,
    SubscriptionsDeliveriesListStatus,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { runSubscriptionTestDelivery } from 'lib/components/Subscriptions/runSubscriptionTestDelivery'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { subscriptionName } from './components/SubscriptionsTable'
import type { subscriptionSceneLogicType } from './subscriptionSceneLogicType'

export type SubscriptionSceneLogicProps = {
    id: string
}

export type DeliveryFeedback = 'positive' | 'negative'
export type DeliveryFeedbackSource = 'email' | 'slack' | 'in_app'

export const FEEDBACK_THANKS_DISPLAY_MS = 1000

export type QueryPlan = NonNullable<SubscriptionApiAiQueryPlan>
export type QueryPlanStep = QueryPlan['steps'][number]

export const PREVIEW_POLL_INTERVAL_MS = 2000
// Matches the preview workflow's generate-activity cap; past this the row will never leave "starting".
export const PREVIEW_POLL_TIMEOUT_MS = 10 * 60 * 1000

function parseCursorFromPaginationUrl(url: string | null | undefined): string | undefined {
    if (!url) {
        return undefined
    }
    try {
        const parsed = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
        const cursor = parsed.searchParams.get('cursor')
        return cursor ?? undefined
    } catch {
        return undefined
    }
}

export const subscriptionSceneLogic = kea<subscriptionSceneLogicType>([
    props({} as SubscriptionSceneLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'subscriptions', 'subscriptionSceneLogic', key]),
    actions({
        deliverSubscription: (id: number) => ({ id }),
        deliverSubscriptionSuccess: true,
        deliverSubscriptionFailure: true,
        setDeliveryStatusFilter: (status: SubscriptionsDeliveriesListStatus | null) => ({ status }),
        submitDeliveryFeedback: (deliveryId: string, feedback: DeliveryFeedback, source: DeliveryFeedbackSource) => ({
            deliveryId,
            feedback,
            source,
        }),
        expireDeliveryThanks: (deliveryId: string) => ({ deliveryId }),
        // Local edits to the frozen plan's HogQL, keyed by step index, before the owner saves.
        setQueryPlanStepHogql: (stepIndex: number, hogql: string) => ({ stepIndex, hogql }),
        resetQueryPlanEdits: true,
    }),
    reducers({
        deliveringSubscriptionId: [
            null as number | null,
            {
                deliverSubscription: (_, { id }) => id,
                deliverSubscriptionSuccess: () => null,
                deliverSubscriptionFailure: () => null,
            },
        ],
        deliveryStatusFilter: [
            null as SubscriptionsDeliveriesListStatus | null,
            {
                setDeliveryStatusFilter: (_, { status }) => status,
            },
        ],
        deliveryFeedback: [
            {} as Record<string, DeliveryFeedback>,
            // localStorage on purpose: feedback is an analytics event, not a DB row — this only keeps
            // the UI honest (and the capture deduped) across reloads on this browser.
            { persist: true },
            {
                submitDeliveryFeedback: (state, { deliveryId, feedback }) => ({ ...state, [deliveryId]: feedback }),
            },
        ],
        // Transient (not persisted): drives the brief "Thanks!" flash before the row settles
        // into showing the recorded option.
        recentlyThankedDeliveries: [
            {} as Record<string, true>,
            {
                submitDeliveryFeedback: (state, { deliveryId }) => ({ ...state, [deliveryId]: true as const }),
                expireDeliveryThanks: (state, { deliveryId }) => {
                    const { [deliveryId]: _removed, ...rest } = state
                    return rest
                },
            },
        ],
        // Pending edits to the frozen plan's HogQL, keyed by step index. Cleared whenever the
        // subscription reloads (the saved plan is the new baseline) or the user resets.
        queryPlanEdits: [
            {} as Record<number, string>,
            {
                setQueryPlanStepHogql: (state, { stepIndex, hogql }) => ({ ...state, [stepIndex]: hogql }),
                resetQueryPlanEdits: () => ({}),
                loadSubscriptionSuccess: () => ({}),
                saveQueryPlanSuccess: () => ({}),
                regeneratePlanSuccess: () => ({}),
            },
        ],
        // A preview rendered from a plan that no longer exists (regenerated) or just changed (saved)
        // is misleading; so is a stale one lingering after a failed run. Clear it in all three cases.
        preview: [
            null as SubscriptionDeliveryApi | null,
            {
                previewSubscriptionFailure: () => null,
                saveQueryPlanSuccess: () => null,
                regeneratePlanSuccess: () => null,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        subscription: [
            null as SubscriptionApi | null,
            {
                loadSubscription: async () => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return null
                    }
                    return await subscriptionsRetrieve(String(getCurrentTeamId()), numericId)
                },
                // Used by the Pause / Resume button on the detail page. PATCH
                // returns the updated subscription so the loader replaces the
                // whole value — no extra GET needed.
                setEnabled: async ({ enabled }: { enabled: boolean }) => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return values.subscription
                    }
                    return await subscriptionsPartialUpdate(String(getCurrentTeamId()), numericId, { enabled })
                },
                // Persist the owner's edits to the frozen plan's HogQL. PATCH returns the updated
                // subscription so the loader replaces the whole value, resetting the editor baseline.
                saveQueryPlan: async () => {
                    const numericId = parseInt(props.id, 10)
                    const plan = values.editedQueryPlan
                    if (!Number.isFinite(numericId) || !plan) {
                        return values.subscription
                    }
                    return await subscriptionsPartialUpdate(String(getCurrentTeamId()), numericId, {
                        ai_query_plan: plan,
                    })
                },
                // Clear the frozen plan; the next report re-plans from the prompt. PATCH returns the
                // updated subscription (ai_query_plan: null), so the editor resets in the same pass.
                regeneratePlan: async () => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return values.subscription
                    }
                    return await subscriptionsPartialUpdate(String(getCurrentTeamId()), numericId, {
                        ai_query_plan: null,
                    })
                },
            },
        ],
        preview: [
            null as SubscriptionDeliveryApi | null,
            {
                clearPreview: () => null,
                // Preview runs in the background: dispatch returns the delivery row id, then poll that
                // row until the workflow finishes (same DB-row polling pattern as exported assets).
                previewSubscription: async (_: void, breakpoint) => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return null
                    }
                    const teamId = String(getCurrentTeamId())
                    const { delivery_id } = await subscriptionsPreviewCreate(teamId, numericId)
                    const deadline = Date.now() + PREVIEW_POLL_TIMEOUT_MS
                    while (true) {
                        await breakpoint(PREVIEW_POLL_INTERVAL_MS)
                        const delivery = await subscriptionsDeliveriesRetrieve(teamId, numericId, delivery_id)
                        if (delivery.status !== 'starting') {
                            if (delivery.status === 'failed' && !delivery.ai_report) {
                                const message = (delivery.error as { message?: unknown } | null)?.message
                                throw new Error(typeof message === 'string' ? message : 'Preview failed')
                            }
                            // A failed-but-degraded run still carries the report + diagnostics — render it.
                            return delivery
                        }
                        if (Date.now() > deadline) {
                            throw new Error('Preview timed out')
                        }
                    }
                },
            },
        ],
        deliveriesPage: [
            null as PaginatedSubscriptionDeliveryListApi | null,
            {
                loadDeliveriesPage: async (targetUrl: string | null) => {
                    const numericId = parseInt(props.id, 10)
                    if (!Number.isFinite(numericId)) {
                        return null
                    }
                    const teamId = String(getCurrentTeamId())
                    const status = values.deliveryStatusFilter ?? undefined
                    if (targetUrl === null) {
                        return await subscriptionsDeliveriesList(teamId, numericId, status ? { status } : {})
                    }
                    const cursor = parseCursorFromPaginationUrl(targetUrl)
                    return await subscriptionsDeliveriesList(teamId, numericId, {
                        ...(cursor ? { cursor } : {}),
                        ...(status ? { status } : {}),
                    })
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.subscription],
            (subscription): Breadcrumb[] => {
                const listCrumb: Breadcrumb = {
                    key: Scene.Subscriptions,
                    name: sceneConfigurations[Scene.Subscriptions].name,
                    path: urls.subscriptions(),
                    iconType: sceneConfigurations[Scene.Subscriptions].iconType || 'default_icon_type',
                }
                if (!subscription) {
                    return [listCrumb]
                }
                return [
                    listCrumb,
                    {
                        key: [Scene.Subscription, subscription.id],
                        name: subscriptionName(subscription),
                        iconType: sceneConfigurations[Scene.Subscription].iconType || 'default_icon_type',
                    },
                ]
            },
        ],
        // The frozen plan with the owner's pending HogQL edits applied, ready to save. Null when there
        // is no plan or no edits — used both to drive the "Save plan" enabled state and as the PATCH body.
        editedQueryPlan: [
            (s) => [s.subscription, s.queryPlanEdits],
            (subscription, queryPlanEdits): QueryPlan | null => {
                const plan = subscription?.ai_query_plan
                if (!plan || Object.keys(queryPlanEdits).length === 0) {
                    return null
                }
                return {
                    ...plan,
                    steps: plan.steps.map((step, index) =>
                        queryPlanEdits[index] !== undefined ? { ...step, hogql: queryPlanEdits[index] } : step
                    ),
                }
            },
        ],
        hasQueryPlanEdits: [(s) => [s.editedQueryPlan], (editedQueryPlan): boolean => editedQueryPlan !== null],
    }),
    listeners(({ actions, values, props, cache, selectors }) => ({
        submitDeliveryFeedback: ({ deliveryId, feedback, source }, _breakpoint, _action, previousState) => {
            posthog.capture('ai_report_feedback', {
                subscription_id: parseInt(props.id, 10),
                delivery_id: deliveryId,
                feedback,
                source,
                // Lets analysis distinguish first votes from switches; consumers take the latest
                // event per person + delivery, so a switched vote simply wins.
                previous_feedback: selectors.deliveryFeedback(previousState)[deliveryId] ?? null,
            })
            // In-app thumbs show a per-row "Thanks" state instead of a toast.
            if (source !== 'in_app') {
                lemonToast.success('Thanks for your feedback')
            }
            // Per-delivery key so spamming replaces the previous timer instead of stacking.
            cache.disposables.add(() => {
                const timerId = setTimeout(() => actions.expireDeliveryThanks(deliveryId), FEEDBACK_THANKS_DISPLAY_MS)
                return () => clearTimeout(timerId)
            }, `deliveryThanks-${deliveryId}`)
        },
        setDeliveryStatusFilter: () => {
            if (values.subscription) {
                void actions.loadDeliveriesPage(null)
            }
        },
        loadSubscriptionSuccess: () => {
            if (values.subscription) {
                void actions.loadDeliveriesPage(null)
            }
        },
        deliverSubscription: async ({ id }) => {
            const result = await runSubscriptionTestDelivery(() =>
                subscriptionsTestDeliveryCreate(String(getCurrentTeamId()), id)
            )
            if (result === 'success') {
                actions.deliverSubscriptionSuccess()
            } else {
                actions.deliverSubscriptionFailure()
            }
        },
        // Test delivery returns 202 before Temporal persists the delivery row. Refetch now (fast path) and
        // again after a short delay so the list usually shows the new row without manual refresh.
        deliverSubscriptionSuccess: async (_, breakpoint) => {
            void actions.loadDeliveriesPage(null)
            await breakpoint(2000)
            void actions.loadDeliveriesPage(null)
        },
        loadDeliveriesPageFailure: ({ errorObject }) => {
            const status = errorObject?.status
            const detail = errorObject?.detail
            const message =
                status === 404
                    ? 'Delivery history is not available.'
                    : typeof detail === 'string'
                      ? detail
                      : 'Could not load delivery history.'
            lemonToast.error(message)
        },
        setEnabledSuccess: ({ subscription }) => {
            if (!subscription) {
                return
            }
            lemonToast.success(subscription.enabled ? 'Subscription enabled' : 'Subscription disabled')
        },
        setEnabledFailure: ({ errorObject }) => {
            // Surface the serializer's actionable message (e.g. re-enabling a Slack
            // sub with no integration) — backend already validates this.
            const detail = errorObject?.detail
            lemonToast.error(typeof detail === 'string' ? detail : 'Could not update subscription')
        },
        regeneratePlanSuccess: () => {
            lemonToast.success('Query plan cleared — the next report will re-plan from your prompt')
        },
        regeneratePlanFailure: ({ errorObject }) => {
            const detail = errorObject?.detail
            lemonToast.error(typeof detail === 'string' ? detail : 'Could not regenerate plan')
        },
        // Refresh the history table so the preview run shows up there too.
        previewSubscriptionSuccess: () => {
            void actions.loadDeliveriesPage(null)
        },
        previewSubscriptionFailure: ({ errorObject }) => {
            const detail = errorObject?.detail
            const message = errorObject instanceof Error ? errorObject.message : undefined
            lemonToast.error(typeof detail === 'string' ? detail : (message ?? 'Could not generate preview'))
        },
        saveQueryPlanSuccess: () => {
            lemonToast.success('Query plan saved')
            posthog.capture('subscription query plan saved', {
                subscription_id: parseInt(props.id, 10),
            })
        },
        saveQueryPlanFailure: ({ errorObject }) => {
            const detail = errorObject?.detail
            lemonToast.error(typeof detail === 'string' ? detail : 'Could not save query plan')
        },
    })),
    urlToAction(({ actions, props, values }) => ({
        // Feedback links in delivered emails/Slack messages land here with these params;
        // capture once, then strip them so a refresh doesn't double-capture.
        [urls.subscription(':id')]: ({ id }, searchParams) => {
            if (id !== props.id) {
                return
            }
            const { feedback_delivery, feedback, feedback_source, ...restSearchParams } = searchParams
            if (!feedback_delivery || (feedback !== 'positive' && feedback !== 'negative')) {
                return
            }
            const deliveryId = String(feedback_delivery)
            if (values.deliveryFeedback[deliveryId]) {
                // Persisted state remembers this delivery — don't re-capture from a re-clicked link.
                lemonToast.info('Your feedback for this report was already recorded')
            } else {
                actions.submitDeliveryFeedback(deliveryId, feedback, feedback_source === 'slack' ? 'slack' : 'email')
            }
            router.actions.replace(router.values.location.pathname, restSearchParams, router.values.hashParams)
        },
    })),
    afterMount(({ actions }) => {
        void actions.loadSubscription()
    }),
])
