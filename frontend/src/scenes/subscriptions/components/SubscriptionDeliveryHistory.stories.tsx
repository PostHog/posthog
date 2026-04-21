import { Meta, StoryObj } from '@storybook/react'
import { useMemo, useState } from 'react'

import type {
    PaginatedSubscriptionDeliveryListApi,
    SubscriptionsDeliveriesListStatus,
} from '~/generated/core/api.schemas'

import { SubscriptionDeliveryHistory } from './SubscriptionDeliveryHistory'
import { MOCK_SUBSCRIPTION_DELIVERIES } from './subscriptionStoryFixtures'

const noopLoadPage = (): void => undefined
const noopTestDelivery = (): void => undefined

// Storybook can't reach the real exports endpoint. Point all preview image lookups at a bundled asset so the
// visual regression snapshot is deterministic.
const STORYBOOK_ASSET_PLACEHOLDER = '/static/blank-dashboard-hog.png'
const buildMockAssetImageUrl = (): string => STORYBOOK_ASSET_PLACEHOLDER

const meta: Meta<typeof SubscriptionDeliveryHistory> = {
    component: SubscriptionDeliveryHistory,
    title: 'Scenes-App/Subscriptions/Subscription delivery history',
    parameters: {
        mockDate: '2026-04-07',
    },
}

export default meta

type Story = StoryObj<typeof SubscriptionDeliveryHistory>

const pageWithRows: PaginatedSubscriptionDeliveryListApi = {
    results: MOCK_SUBSCRIPTION_DELIVERIES,
    next: null,
    previous: null,
}

export const WithDeliveries: Story = {
    render: () => {
        const [deliveryStatusFilter, setDeliveryStatusFilter] = useState<SubscriptionsDeliveriesListStatus | null>(null)
        const results = useMemo(
            () =>
                deliveryStatusFilter
                    ? MOCK_SUBSCRIPTION_DELIVERIES.filter((d) => d.status === deliveryStatusFilter)
                    : MOCK_SUBSCRIPTION_DELIVERIES,
            [deliveryStatusFilter]
        )
        return (
            <SubscriptionDeliveryHistory
                deliveriesPage={{ ...pageWithRows, results }}
                deliveriesPageLoading={false}
                loadDeliveriesPage={noopLoadPage}
                deliveryStatusFilter={deliveryStatusFilter}
                onDeliveryStatusFilterChange={setDeliveryStatusFilter}
                onTestDelivery={noopTestDelivery}
                buildAssetImageUrl={buildMockAssetImageUrl}
            />
        )
    },
}

// Covers both expand states for one PR-specific feature: the expand affordance on a collapsed row with a summary,
// and the rendered summary content inside an expanded row.
const EXPANDED_SUMMARY_STORY_IDS: ReadonlySet<string> = new Set(['del-1'])

export const WithExpandedSummary: Story = {
    args: {
        deliveriesPage: pageWithRows,
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        initiallyExpandedDeliveryIds: EXPANDED_SUMMARY_STORY_IDS,
        buildAssetImageUrl: buildMockAssetImageUrl,
    },
}

export const Empty: Story = {
    args: {
        deliveriesPage: { results: [], next: null, previous: null },
        deliveriesPageLoading: false,
        loadDeliveriesPage: noopLoadPage,
        onTestDelivery: noopTestDelivery,
        testDeliveryLoading: false,
        buildAssetImageUrl: buildMockAssetImageUrl,
    },
}
