import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
    NodeKind,
} from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'

import type { AlertType } from '../types'
import { ManageAlertsModal } from './ManageAlertsModal'

const insightShortId = 'checkout-volume' as InsightShortId
const createdBy = {
    id: 1,
    uuid: '018f59f3-4f2f-7c89-b389-73b99b91f442',
    distinct_id: 'storybook-user',
    first_name: 'Hedge Hog',
    email: 'hedge@example.com',
    hedgehog_config: null,
}

const makeAlert = (overrides: Partial<AlertType>): AlertType =>
    ({
        id: 'alert-volume',
        name: 'Upload volume above 10,000',
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
            short_id: insightShortId,
            name: 'Checkout volume',
            derived_name: 'Checkout volume',
        },
        ...overrides,
    }) as AlertType

const alerts = [
    makeAlert({}),
    makeAlert({
        id: 'alert-anomaly',
        name: 'Unusual upload volume',
        state: AlertState.FIRING,
        detector_config: {
            type: 'zscore',
            threshold: 0.95,
            window: 90,
        },
    }),
    makeAlert({
        id: 'alert-disabled',
        name: 'Upload volume below 100',
        enabled: false,
        threshold: {
            configuration: {
                type: InsightThresholdType.ABSOLUTE,
                bounds: { lower: 100 },
            },
        },
    }),
]

const insightQuery = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: 'file uploaded' }],
    },
}

const meta: Meta<typeof ManageAlertsModal> = {
    component: ManageAlertsModal,
    title: 'Products/Alerts/Insight alerts modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-16',
        featureFlags: [FEATURE_FLAGS.ALERTS_REDESIGNED_EDIT_MODAL],
        testOptions: { viewport: { width: 1000, height: 700 } },
    },
    args: {
        isOpen: true,
        insightId: 101,
        insightShortId,
        canCreateAlertForInsight: true,
        insightQuery,
        insightLogicProps: {
            dashboardItemId: insightShortId,
            cachedInsight: {
                id: 101,
                short_id: insightShortId,
                name: 'Checkout volume',
                query: insightQuery,
                alerts,
            },
        },
        onClose: () => {},
        onCreateAlert: () => {},
        onEditAlert: () => {},
    },
}

export default meta

type Story = StoryObj<typeof meta>

export const WithAlerts: Story = {}
