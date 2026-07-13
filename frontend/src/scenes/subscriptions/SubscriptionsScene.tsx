import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { HedgehogMagnifyingGlass } from '@posthog/brand/hoggies'
import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonModal, Link } from '@posthog/lemon-ui'
import type { SubscriptionApi } from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { EditSubscription } from 'lib/components/Subscriptions/views/EditSubscription'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { SubscriptionsFiltersBar } from './components/SubscriptionsFiltersBar'
import {
    SubscriptionsTable,
    isSubscriptionEnabled,
    subscriptionEditHref,
    subscriptionName,
} from './components/SubscriptionsTable'
import { SubscriptionsTab, subscriptionsSceneLogic } from './subscriptionsSceneLogic'

function SubscriptionsRowActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { deleteSubscriptionSuccess, deliverSubscription, setSubscriptionEnabled } =
        useActions(subscriptionsSceneLogic)
    const { deliveringSubscriptionId, togglingEnabledId } = useValues(subscriptionsSceneLogic)
    const href = subscriptionEditHref(sub)
    const isDelivering = deliveringSubscriptionId === sub.id
    const isToggling = togglingEnabledId === sub.id
    const enabled = isSubscriptionEnabled(sub)

    return (
        <LemonMenu
            items={[
                ...(href
                    ? [
                          {
                              label: 'Edit subscription',
                              onClick: () => push(href),
                          },
                      ]
                    : []),
                {
                    label: enabled ? 'Disable subscription' : 'Enable subscription',
                    'data-attr': 'subscription-list-item-toggle-enabled',
                    disabledReason: isToggling ? 'Updating…' : null,
                    onClick: () => setSubscriptionEnabled(sub.id, !enabled),
                },
                ...(enabled
                    ? [
                          {
                              label: 'Test delivery',
                              'data-attr': 'subscription-list-item-manual-deliver',
                              disabledReason: isDelivering ? 'Sending test delivery…' : null,
                              onClick: () => deliverSubscription(sub.id),
                          },
                      ]
                    : []),
                {
                    label: 'Delete',
                    status: 'danger' as const,
                    onClick: () =>
                        void deleteWithUndo({
                            endpoint: `projects/${String(getCurrentTeamId())}/subscriptions`,
                            object: {
                                id: sub.id,
                                name: subscriptionName(sub),
                            },
                            callback: () => deleteSubscriptionSuccess(),
                        }),
                },
            ]}
        >
            <LemonButton
                icon={isDelivering || isToggling ? <Spinner /> : <IconEllipsis />}
                size="small"
                aria-label="Subscription actions"
                disabled={isDelivering || isToggling}
            />
        </LemonMenu>
    )
}

export function SubscriptionsScene(): JSX.Element {
    const {
        subscriptions,
        subscriptionsLoading,
        subscriptionsListAwaitingDebouncedFetch,
        pagination,
        search,
        createdByUuid,
        currentTab,
        subscriptionsSorting,
        targetTypeFilter,
        subscriptionModalId,
    } = useValues(subscriptionsSceneLogic)
    const { setCurrentTab, setSubscriptionsSorting } = useActions(subscriptionsSceneLogic)
    const aiSubscriptionsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')

    const isFiltered =
        Boolean(search.trim()) ||
        createdByUuid !== null ||
        targetTypeFilter !== null ||
        currentTab !== SubscriptionsTab.All

    const subscriptionTabs: LemonTab<SubscriptionsTab>[] = [
        { key: SubscriptionsTab.All, label: 'All subscriptions' },
        { key: SubscriptionsTab.Mine, label: 'My subscriptions' },
        { key: SubscriptionsTab.Dashboard, label: 'Dashboard' },
        { key: SubscriptionsTab.Insight, label: 'Insight' },
        ...(aiSubscriptionsEnabled ? [{ key: SubscriptionsTab.AI, label: 'Prompt' }] : []),
    ]
    const showProductIntroduction =
        subscriptions.length === 0 && !subscriptionsLoading && !isFiltered && !subscriptionsListAwaitingDebouncedFetch

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Subscriptions].name}
                description={sceneConfigurations[Scene.Subscriptions].description}
                resourceType={{ type: 'inbox' }}
                actions={
                    aiSubscriptionsEnabled ? (
                        <LemonButton
                            type="primary"
                            data-attr="new-subscription-button"
                            onClick={() => router.actions.push(urls.subscriptionNew())}
                        >
                            New prompt subscription
                        </LemonButton>
                    ) : undefined
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(newKey) => setCurrentTab(newKey)}
                tabs={subscriptionTabs}
                sceneInset
            />
            <div className="py-8 flex-1 min-h-0 flex flex-col gap-4 max-w-full">
                {showProductIntroduction ? (
                    <ProductIntroduction
                        productName="Subscriptions"
                        productKey={ProductKey.SUBSCRIPTIONS}
                        thingName="subscription"
                        titleOverride="No subscriptions yet"
                        description="Get recurring email or Slack digests, or scheduled exports from insights and dashboards. Use them for weekly rollups, stakeholder updates, or wiring metrics into your own systems."
                        isEmpty
                        customHog={HedgehogMagnifyingGlass}
                        hogLayout="responsive"
                        useMainContentContainerQueries
                        docsURL="https://posthog.com/docs/user-guides/subscriptions"
                        actionElementOverride={
                            <span className="italic">
                                Open a <Link to={urls.dashboards()}>dashboard</Link> or{' '}
                                <Link to={urls.insights()}>saved insight</Link>, open the side panel, and click{' '}
                                &quot;Subscribe&quot; to configure the options.
                            </span>
                        }
                    />
                ) : (
                    <>
                        <SubscriptionsFiltersBar />
                        <SubscriptionsTable
                            dataSource={subscriptions}
                            loading={subscriptionsLoading}
                            pagination={pagination}
                            sorting={subscriptionsSorting}
                            onSort={setSubscriptionsSorting}
                            renderRowActions={(sub) => <SubscriptionsRowActions sub={sub} />}
                        />
                    </>
                )}
            </div>
            {subscriptionModalId !== null && (
                <LemonModal isOpen onClose={() => router.actions.push(urls.subscriptions())} simple={false} width={650}>
                    <EditSubscription
                        id={subscriptionModalId}
                        onCancel={() => router.actions.push(urls.subscriptions())}
                        onDelete={() => router.actions.push(urls.subscriptions())}
                    />
                </LemonModal>
            )}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SubscriptionsScene,
    logic: subscriptionsSceneLogic,
}
