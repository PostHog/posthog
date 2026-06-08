import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SubscriptionDeliveryHistory } from './components/SubscriptionDeliveryHistory'
import { isSubscriptionEnabled, subscriptionEditHref, subscriptionName } from './components/SubscriptionsTable'
import { SubscriptionSummary } from './components/SubscriptionSummary'
import { subscriptionSceneLogic } from './subscriptionSceneLogic'
import { subscriptionsSceneLogic } from './subscriptionsSceneLogic'

function SubscriptionDetailActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { setEnabled } = useActions(subscriptionSceneLogic)
    const { subscriptionLoading } = useValues(subscriptionSceneLogic)
    const editHref = subscriptionEditHref(sub)
    const enabled = isSubscriptionEnabled(sub)

    const deleteSubscription = (): void => {
        const name = subscriptionName(sub)
        void deleteWithUndo({
            endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
            object: {
                id: sub.id,
                name,
            },
            callback: () => {
                subscriptionsSceneLogic.findMounted()?.actions.deleteSubscriptionSuccess()
                push(urls.subscriptions())
            },
        })
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonTag type={enabled ? 'success' : 'danger'} data-attr="subscription-status-tag">
                {enabled ? 'Enabled' : 'Disabled'}
            </LemonTag>
            <LemonButton
                type="secondary"
                onClick={() => setEnabled({ enabled: !enabled })}
                loading={subscriptionLoading}
                data-attr="subscription-toggle-enabled"
            >
                {enabled ? 'Disable subscription' : 'Enable subscription'}
            </LemonButton>
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

export function SubscriptionScene(): JSX.Element {
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
            {showNotFound ? (
                <NotFound object="subscription" />
            ) : (
                <div className="py-8 flex-1 min-h-0 flex flex-col gap-6 max-w-full">
                    <SceneTitleSection
                        name={subscription ? subscriptionName(subscription) : 'Subscription'}
                        description={null}
                        resourceType={{ type: 'inbox' }}
                        isLoading={subscriptionLoading}
                        actions={subscription ? <SubscriptionDetailActions sub={subscription} /> : undefined}
                    />
                    {subscription ? (
                        // Mute the body when the subscription is paused — the LemonTag in the
                        // header is the explicit signal; this is the at-a-glance reinforcement.
                        <div className={isSubscriptionEnabled(subscription) ? '' : 'opacity-60'}>
                            <SubscriptionSummary sub={subscription} />
                        </div>
                    ) : null}
                    {deliveriesEnabled ? (
                        <SubscriptionDeliveryHistory
                            deliveriesPage={deliveriesPage}
                            deliveriesPageLoading={deliveriesPageLoading}
                            loadDeliveriesPage={loadDeliveriesPage}
                            deliveryStatusFilter={deliveryStatusFilter}
                            onDeliveryStatusFilterChange={setDeliveryStatusFilter}
                            onTestDelivery={subscription ? () => deliverSubscription(subscription.id) : undefined}
                            testDeliveryLoading={Boolean(subscription && deliveringSubscriptionId === subscription.id)}
                        />
                    ) : null}
                </div>
            )}
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
