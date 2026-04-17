import { Meta, StoryObj } from '@storybook/react'
import { useState, type ComponentProps } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import type { PaginationManual } from '@posthog/lemon-ui'

import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { FrequencyEnumApi, TargetTypeEnumApi } from '~/generated/core/api.schemas'

import { SubscriptionsTable } from './SubscriptionsTable'

const MOCK_USER = {
    id: 1,
    uuid: '01863799-062b-0000-8a61-b2842d5f8642',
    email: 'matt@posthog.com',
    first_name: 'Matt',
    last_name: 'P',
    hedgehog_config: null,
} as const

const MOCK_SUBSCRIPTIONS: SubscriptionApi[] = [
    {
        id: 1,
        insight: 101,
        dashboard: null,
        insight_short_id: 'abc123',
        resource_name: 'North star metric',
        title: 'This is a really long subscription name that does something important for the team every week',
        dashboard_export_insights: [],
        target_type: TargetTypeEnumApi.Email,
        target_value:
            'matt.p@posthog.com,matt.p2@posthog.com,matt.p3@posthog.com,matt.p4@posthog.com,matt.p5@posthog.com',
        frequency: FrequencyEnumApi.Weekly,
        interval: 1,
        start_date: '2022-01-01T00:00:00Z',
        created_at: '2023-04-27T10:04:37.977401Z',
        created_by: MOCK_USER,
        summary: 'sent every week',
        next_delivery_date: '2026-04-07T17:00:00Z',
        deleted: false,
    },
    {
        id: 2,
        insight: null,
        dashboard: 501,
        insight_short_id: null,
        resource_name: 'Company overview',
        title: 'Some slack notification that does something',
        dashboard_export_insights: [101, 102],
        target_type: TargetTypeEnumApi.Slack,
        target_value: 'C12345|#alerts-analytics-platform',
        frequency: FrequencyEnumApi.Daily,
        interval: 1,
        start_date: '2022-01-01T00:00:00Z',
        created_at: '2023-04-27T10:04:37.977401Z',
        created_by: MOCK_USER,
        summary: 'sent every day',
        next_delivery_date: '2026-04-08T09:00:00Z',
        deleted: false,
        integration_id: 1,
    },
    {
        id: 3,
        insight: 103,
        dashboard: null,
        insight_short_id: 'ghi789',
        resource_name: 'Weekly KPIs',
        title: 'Some test on an insight',
        dashboard_export_insights: [],
        target_type: TargetTypeEnumApi.Email,
        target_value: 'matt.p@posthog.com',
        frequency: FrequencyEnumApi.Monthly,
        interval: 1,
        start_date: '2022-01-01T00:00:00Z',
        created_at: '2023-04-27T10:04:37.977401Z',
        created_by: MOCK_USER,
        summary: 'sent every month',
        next_delivery_date: null,
        deleted: false,
    },
    {
        id: 4,
        insight: 104,
        dashboard: null,
        insight_short_id: 'webhook-insight',
        resource_name: 'Activation funnel',
        title: 'Webhook delivery to internal automation',
        dashboard_export_insights: [],
        target_type: TargetTypeEnumApi.Webhook,
        target_value: 'https://hooks.example.com/services/posthog/subscriptions/abc123def456',
        frequency: FrequencyEnumApi.Weekly,
        interval: 1,
        start_date: '2022-01-01T00:00:00Z',
        created_at: '2023-04-27T10:04:37.977401Z',
        created_by: MOCK_USER,
        summary: 'sent every week',
        next_delivery_date: '2026-04-14T12:00:00Z',
        deleted: false,
    },
]

const PAGINATION_PAGE_SIZE = 20

const paginationFor = (rows: SubscriptionApi[]): PaginationManual => ({
    controlled: true,
    pageSize: PAGINATION_PAGE_SIZE,
    currentPage: 1,
    // Match subscriptionsSceneLogic: usePagination treats 0 as missing entryCount.
    entryCount: Math.max(rows.length, 1),
    onBackward: () => undefined,
    onForward: () => undefined,
})

function buildMockSubscriptions(total: number): SubscriptionApi[] {
    return Array.from({ length: total }, (_, i) => {
        const n = i + 1
        const isInsight = i % 2 === 0
        const isSlack = i % 3 === 0
        return {
            id: n,
            insight: isInsight ? 1000 + n : null,
            dashboard: isInsight ? null : 2000 + n,
            insight_short_id: isInsight ? `short${n}` : null,
            resource_name: `Quarterly metrics ${n}`,
            title: `Digest ${n}`,
            dashboard_export_insights: [],
            target_type: isSlack ? TargetTypeEnumApi.Slack : TargetTypeEnumApi.Email,
            target_value: isSlack ? `C${n}|#channel-${n}` : `analyst${n}@posthog.com`,
            frequency: FrequencyEnumApi.Weekly,
            interval: 1,
            start_date: '2022-01-01T00:00:00Z',
            created_at: '2023-04-27T10:04:37.977401Z',
            created_by: MOCK_USER,
            summary: 'sent every week',
            next_delivery_date: '2026-04-07T17:00:00Z',
            deleted: false,
            ...(isSlack ? { integration_id: 1 } : {}),
        }
    })
}

const MOCK_SUBSCRIPTIONS_MULTI_PAGE = buildMockSubscriptions(45)

const meta: Meta<typeof SubscriptionsTable> = {
    title: 'Scenes-App/Subscriptions/SubscriptionsTable',
    component: SubscriptionsTable,
    parameters: {
        layout: 'padded',
        mockDate: '2026-04-07',
    },
    decorators: [
        (Story): JSX.Element => (
            <div className="max-w-6xl">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SubscriptionsTable>

function StoryShell(props: Omit<ComponentProps<typeof SubscriptionsTable>, 'renderRowActions'>): JSX.Element {
    return (
        <SubscriptionsTable
            {...props}
            renderRowActions={() => (
                <LemonButton icon={<IconEllipsis />} size="small" aria-label="Subscription actions" />
            )}
        />
    )
}

function MultiPageStoryShell(): JSX.Element {
    const [page, setPage] = useState(1)
    const total = MOCK_SUBSCRIPTIONS_MULTI_PAGE.length
    const pageCount = Math.ceil(total / PAGINATION_PAGE_SIZE)
    const slice = MOCK_SUBSCRIPTIONS_MULTI_PAGE.slice((page - 1) * PAGINATION_PAGE_SIZE, page * PAGINATION_PAGE_SIZE)

    return (
        <SubscriptionsTable
            dataSource={slice}
            loading={false}
            pagination={{
                controlled: true,
                pageSize: PAGINATION_PAGE_SIZE,
                currentPage: page,
                entryCount: Math.max(total, 1),
                onBackward: page > 1 ? () => setPage((p) => Math.max(1, p - 1)) : undefined,
                onForward: page < pageCount ? () => setPage((p) => Math.min(pageCount, p + 1)) : undefined,
            }}
            renderRowActions={() => (
                <LemonButton icon={<IconEllipsis />} size="small" aria-label="Subscription actions" />
            )}
        />
    )
}

export const Default: Story = {
    render: () => (
        <StoryShell dataSource={MOCK_SUBSCRIPTIONS} loading={false} pagination={paginationFor(MOCK_SUBSCRIPTIONS)} />
    ),
}

export const WithPagination: Story = {
    render: () => <MultiPageStoryShell />,
}
