import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, Link } from '@posthog/lemon-ui'

import { DetectiveHog } from 'lib/components/hedgehogs'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'
import { AvailableFeature } from '~/types'

import { SubscriptionsFiltersBar } from './SubscriptionsFiltersBar'
import { SubscriptionsLoadingSkeleton } from './SubscriptionsLoadingSkeleton'
import { SubscriptionsTab, subscriptionsSceneLogic } from './subscriptionsSceneLogic'
import { SubscriptionsTable, subscriptionName } from './SubscriptionsTable'

function editHref(sub: SubscriptionApi): string | null {
    if (sub.insight && sub.insight_short_id) {
        return urls.insightSubcription(sub.insight_short_id as InsightShortId, String(sub.id))
    }
    if (sub.dashboard) {
        return urls.dashboardSubscription(sub.dashboard, String(sub.id))
    }
    return null
}

function SubscriptionsRowActions({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const { push } = useActions(router)
    const { deleteSubscriptionSuccess, deliverSubscription } = useActions(subscriptionsSceneLogic)
    const { deliveringSubscriptionId } = useValues(subscriptionsSceneLogic)
    const href = editHref(sub)
    const isDelivering = deliveringSubscriptionId === sub.id

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
                    label: 'Test delivery',
                    'data-attr': 'subscription-list-item-manual-deliver',
                    disabledReason: isDelivering ? 'Sending test delivery…' : null,
                    onClick: () => deliverSubscription(sub.id),
                },
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
                icon={isDelivering ? <Spinner /> : <IconEllipsis />}
                size="small"
                aria-label="Subscription actions"
                disabled={isDelivering}
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
    } = useValues(subscriptionsSceneLogic)
    const { setCurrentTab, setSubscriptionsSorting } = useActions(subscriptionsSceneLogic)

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
    ]
    const showProductIntroduction =
        subscriptions.length === 0 && !subscriptionsLoading && !isFiltered && !subscriptionsListAwaitingDebouncedFetch

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Subscriptions].name}
                description={sceneConfigurations[Scene.Subscriptions].description}
                resourceType={{ type: 'inbox' }}
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(newKey) => setCurrentTab(newKey)}
                tabs={subscriptionTabs}
                sceneInset
            />
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
                <div className="flex flex-col gap-4 max-w-full">
                    {showProductIntroduction ? (
                        <ProductIntroduction
                            productName="Subscriptions"
                            productKey={ProductKey.SUBSCRIPTIONS}
                            thingName="subscription"
                            titleOverride="No subscriptions yet"
                            description="Get recurring email or Slack digests, or scheduled exports from insights and dashboards. Use them for weekly rollups, stakeholder updates, or wiring metrics into your own systems."
                            isEmpty
                            customHog={DetectiveHog}
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
            </PayGateMini>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SubscriptionsScene,
    logic: subscriptionsSceneLogic,
}
