import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneExport, type SceneProps } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AvailableFeature } from '~/types'

import { SubscriptionDeliveryHistory } from './components/SubscriptionDeliveryHistory'
import { SubscriptionsLoadingSkeleton } from './components/SubscriptionsLoadingSkeleton'
import { subscriptionEditHref, subscriptionName } from './components/SubscriptionsTable'
import { SubscriptionSummary } from './components/SubscriptionSummary'
import { subscriptionSceneLogic } from './subscriptionSceneLogic'
import { subscriptionsSceneLogic } from './subscriptionsSceneLogic'

function SubscriptionDetailActions({ sub, tabId }: { sub: SubscriptionApi; tabId?: string }): JSX.Element {
    const { push } = useActions(router)
    const { activeTabId } = useValues(sceneLogic)
    const listTabId = tabId ?? activeTabId ?? undefined
    const editHref = subscriptionEditHref(sub)

    const deleteSubscription = (): void => {
        const name = subscriptionName(sub)
        void deleteWithUndo({
            endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
            object: {
                id: sub.id,
                name,
            },
            callback: () => {
                if (listTabId) {
                    subscriptionsSceneLogic.findMounted({ tabId: listTabId })?.actions.deleteSubscriptionSuccess()
                }
                push(urls.subscriptions())
            },
        })
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            {editHref ? (
                <LemonButton type="secondary" onClick={() => push(editHref)}>
                    Edit subscription
                </LemonButton>
            ) : null}
            <LemonButton
                type="secondary"
                status="danger"
                data-attr="subscription-detail-delete"
                onClick={deleteSubscription}
            >
                Delete
            </LemonButton>
        </div>
    )
}

export function SubscriptionScene({ tabId }: SceneProps): JSX.Element {
    const {
        subscription,
        subscriptionLoading,
        deliveriesEnabled,
        deliveriesPage,
        deliveriesPageLoading,
        deliveringSubscriptionId,
        deliveryStatusFilter,
    } = useValues(subscriptionSceneLogic)
    const { loadDeliveriesPage, deliverSubscription, setDeliveryStatusFilter } = useActions(subscriptionSceneLogic)

    const showNotFound = !subscriptionLoading && !subscription

    return (
        <SceneContent>
            <PayGateMini
                feature={AvailableFeature.SUBSCRIPTIONS}
                handleSubmit={() => undefined}
                background={false}
                className="py-8 flex-1 min-h-0 flex flex-col"
                docsLink="https://posthog.com/docs/user-guides/subscriptions"
                loadingSkeleton={
                    <div className="py-8 flex-1 min-h-0 flex flex-col w-full">
                        <SubscriptionsLoadingSkeleton />
                    </div>
                }
            >
                {showNotFound ? (
                    <NotFound object="subscription" />
                ) : (
                    <div className="flex flex-col gap-6 max-w-full">
                        <SceneTitleSection
                            name={subscription ? subscriptionName(subscription) : 'Subscription'}
                            description={null}
                            resourceType={{ type: 'inbox' }}
                            isLoading={subscriptionLoading}
                            actions={
                                subscription ? (
                                    <SubscriptionDetailActions sub={subscription} tabId={tabId} />
                                ) : undefined
                            }
                        />
                        {subscription ? <SubscriptionSummary sub={subscription} /> : null}
                        {deliveriesEnabled ? (
                            <SubscriptionDeliveryHistory
                                deliveriesPage={deliveriesPage}
                                deliveriesPageLoading={deliveriesPageLoading}
                                loadDeliveriesPage={loadDeliveriesPage}
                                deliveryStatusFilter={deliveryStatusFilter}
                                onDeliveryStatusFilterChange={setDeliveryStatusFilter}
                                onTestDelivery={subscription ? () => deliverSubscription(subscription.id) : undefined}
                                testDeliveryLoading={Boolean(
                                    subscription && deliveringSubscriptionId === subscription.id
                                )}
                            />
                        ) : null}
                    </div>
                )}
            </PayGateMini>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SubscriptionScene,
    logic: subscriptionSceneLogic,
    paramsToProps: ({ params: { subscriptionId } }): { id: string } => ({
        id: String(subscriptionId ?? ''),
    }),
}
