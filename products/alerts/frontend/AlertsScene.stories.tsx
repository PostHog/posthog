import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'
import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'

import { AlertType } from './types'

const createdBy = {
    id: 1,
    uuid: '018f59f3-4f2f-7c89-b389-73b99b91f442',
    distinct_id: 'storybook-user',
    first_name: 'Hedge Hog',
    email: 'hedge@example.com',
}

const makeAlert = (overrides: Partial<AlertType>): AlertType =>
    ({
        id: 'alert-1',
        name: 'Weekly active users above 10,000',
        enabled: true,
        state: AlertState.NOT_FIRING,
        calculation_interval: AlertCalculationInterval.HOURLY,
        last_checked_at: '2026-07-16T16:45:00Z',
        last_notified_at: '2026-07-14T13:30:00Z',
        created_at: '2026-06-01T09:00:00Z',
        created_by: createdBy,
        subscribed_users: [createdBy],
        checks: [],
        config: {
            type: 'TrendsAlertConfig',
            series_index: 0,
            check_ongoing_interval: false,
        },
        threshold: {
            configuration: {
                type: InsightThresholdType.ABSOLUTE,
                bounds: { upper: 10000 },
            },
        },
        condition: { type: AlertConditionType.ABSOLUTE_VALUE },
        insight: {
            id: 101,
            short_id: 'weekly-active-users',
            name: 'Weekly active users',
            derived_name: 'Weekly active users',
        },
        ...overrides,
    }) as AlertType

const alerts: AlertType[] = [
    makeAlert({
        id: 'alert-firing',
        name: 'Checkout conversion below 40%',
        state: AlertState.FIRING,
        last_notified_at: '2026-07-16T16:45:00Z',
        insight: {
            id: 102,
            short_id: 'checkout-conversion',
            name: 'Checkout conversion',
            derived_name: 'Checkout conversion',
        } as AlertType['insight'],
    }),
    makeAlert({ id: 'alert-healthy' }),
    makeAlert({
        id: 'alert-disabled',
        name: 'Daily signups above 1,000',
        enabled: false,
        calculation_interval: AlertCalculationInterval.DAILY,
        last_notified_at: '',
        insight: {
            id: 103,
            short_id: 'daily-signups',
            name: 'Daily signups',
            derived_name: 'Daily signups',
        } as AlertType['insight'],
    }),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Alerts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-16',
        pageUrl: urls.alerts(),
        testOptions: { viewport: { width: 1300, height: 900 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/alerts/': toPaginatedResponse(alerts),
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const ListView: Story = {}

export const EmptyState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}
