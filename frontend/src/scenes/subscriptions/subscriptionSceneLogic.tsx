import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { runSubscriptionTestDelivery } from 'lib/components/Subscriptions/runSubscriptionTestDelivery'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    subscriptionsDeliveriesList,
    subscriptionsPartialUpdate,
    subscriptionsRetrieve,
    subscriptionsTestDeliveryCreate,
} from '~/generated/core/api'
import type {
    PaginatedSubscriptionDeliveryListApi,
    SubscriptionApi,
    SubscriptionsDeliveriesListStatus,
} from '~/generated/core/api.schemas'
import { Breadcrumb } from '~/types'

import { subscriptionName } from './components/SubscriptionsTable'
import type { subscriptionSceneLogicType } from './subscriptionSceneLogicType'

export type SubscriptionSceneLogicProps = {
    id: string
    tabId?: string
}

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
    key(({ id, tabId }) => `${tabId ?? ''}-${id}`),
    path((key) => ['scenes', 'subscriptions', 'subscriptionSceneLogic', key]),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        deliverSubscription: (id: number) => ({ id }),
        deliverSubscriptionSuccess: true,
        deliverSubscriptionFailure: true,
        setDeliveryStatusFilter: (status: SubscriptionsDeliveriesListStatus | null) => ({ status }),
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
            },
        ],
        deliveriesPage: [
            null as PaginatedSubscriptionDeliveryListApi | null,
            {
                loadDeliveriesPage: async (targetUrl: string | null) => {
                    if (!values.deliveriesEnabled) {
                        return null
                    }
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
        deliveriesEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => Boolean(featureFlags[FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS]),
        ],
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
    }),
    subscriptions(({ actions, values }) => ({
        featureFlags: (featureFlags, oldFeatureFlags) => {
            const enabled = Boolean(featureFlags[FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS])
            const wasEnabled = Boolean(oldFeatureFlags?.[FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS])
            if (enabled === wasEnabled) {
                return
            }
            if (!enabled) {
                actions.loadDeliveriesPageSuccess(null, null)
            } else if (values.subscription) {
                void actions.loadDeliveriesPage(null)
            }
        },
    })),
    listeners(({ actions, values }) => ({
        setDeliveryStatusFilter: () => {
            if (values.deliveriesEnabled && values.subscription) {
                void actions.loadDeliveriesPage(null)
            }
        },
        loadSubscriptionSuccess: () => {
            if (values.deliveriesEnabled && values.subscription) {
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
            if (!values.deliveriesEnabled) {
                return
            }
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
    })),
    afterMount(({ actions }) => {
        void actions.loadSubscription()
    }),
])
