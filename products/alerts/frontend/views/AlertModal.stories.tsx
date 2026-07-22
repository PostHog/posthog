import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'

import type { AlertCheck, AlertType } from '../types'
import { EditAlertModal } from './EditAlertModal'

const createdBy = {
    id: 1,
    uuid: '018f59f3-4f2f-7c89-b389-73b99b91f442',
    distinct_id: 'storybook-user',
    first_name: 'Hedge Hog',
    email: 'hedge@example.com',
    hedgehog_config: null,
}

function makeChecks(values: number[]): AlertCheck[] {
    return values.map((calculatedValue, index) => ({
        id: `check-${index}`,
        created_at: `2026-07-16T${String(12 + index).padStart(2, '0')}:00:00Z`,
        calculated_value: calculatedValue,
        state: AlertState.NOT_FIRING,
        targets_notified: false,
    }))
}

const makeAlert = (overrides: Partial<AlertType>): AlertType =>
    ({
        id: 'alert-trends',
        name: 'Large file uploads',
        enabled: true,
        state: AlertState.NOT_FIRING,
        calculation_interval: AlertCalculationInterval.HOURLY,
        last_checked_at: '2026-07-16T16:45:00Z',
        last_notified_at: '2026-07-14T13:30:00Z',
        created_at: '2026-06-01T09:00:00Z',
        created_by: createdBy,
        subscribed_users: [createdBy],
        checks: makeChecks([4200000, 5100000, 4800000, 6700000, 7200000, 6100000, 8300000, 9400000]),
        config: {
            type: 'TrendsAlertConfig',
            series_index: 0,
            check_ongoing_interval: false,
        },
        threshold: {
            configuration: {
                type: InsightThresholdType.ABSOLUTE,
                bounds: { lower: 1, upper: 10000000 },
            },
        },
        condition: { type: AlertConditionType.ABSOLUTE_VALUE },
        insight: {
            id: 104,
            short_id: 'large-file-uploads',
            name: 'Large file uploads',
            derived_name: 'Large file uploads',
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: 'file uploaded',
                            math: 'avg',
                            math_property: 'file_size_b',
                        },
                    ],
                },
            },
        },
        ...overrides,
    }) as AlertType

const trendsAlert = makeAlert({})

const funnelAlert = makeAlert({
    id: 'alert-funnel',
    name: 'Checkout conversion below 40%',
    checks: makeChecks([0.52, 0.49, 0.47, 0.44, 0.42, 0.39, 0.37, 0.35]),
    config: {
        type: 'FunnelsAlertConfig',
        funnel_step: 1,
        metric: 'conversion_from_start',
        check_ongoing_interval: false,
    },
    insight: {
        id: 105,
        short_id: 'checkout-funnel',
        name: 'Checkout funnel',
        derived_name: 'Checkout funnel',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.FunnelsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: 'checkout started', name: 'Checkout started' },
                    { kind: NodeKind.EventsNode, event: 'order completed', name: 'Order completed' },
                ],
            },
        },
    } as unknown as AlertType['insight'],
    threshold: {
        configuration: {
            type: InsightThresholdType.PERCENTAGE,
            bounds: { lower: 0.4 },
        },
    },
})

const hogQLAlert = makeAlert({
    id: 'alert-hogql',
    name: 'Queue depth above 1,000',
    checks: makeChecks([720, 810, 760, 880, 920, 1050, 980, 1200]),
    config: {
        type: 'HogQLAlertConfig',
        column: 'queue_depth',
        evaluation: 'last_row',
        label_column: 'recorded_at',
    },
    insight: {
        id: 106,
        short_id: 'queue-depth',
        name: 'Queue depth',
        derived_name: 'Queue depth',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT recorded_at, queue_depth FROM queue_metrics ORDER BY recorded_at',
            },
        },
    } as unknown as AlertType['insight'],
    threshold: {
        configuration: {
            type: InsightThresholdType.ABSOLUTE,
            bounds: { upper: 1000 },
        },
    },
})

const meta: Meta<typeof EditAlertModal> = {
    component: EditAlertModal,
    title: 'Products/Alerts/Alert modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-16',
        featureFlags: [FEATURE_FLAGS.ALERTS_REDESIGNED_EDIT_MODAL, FEATURE_FLAGS.ALERTS_INLINE_NOTIFICATIONS],
        testOptions: { viewport: { width: 1300, height: 900 } },
    },
}

export default meta

type StoryInsightType = 'trends' | 'funnel' | 'hogql'

interface AlertTypeStoryProps {
    insightType: StoryInsightType
}

const storyAlerts: Record<StoryInsightType, AlertType> = {
    trends: trendsAlert,
    funnel: funnelAlert,
    hogql: hogQLAlert,
}

const alertsById = Object.fromEntries(Object.values(storyAlerts).map((alert) => [alert.id, alert]))

function EditAlertStory({ insightType }: AlertTypeStoryProps): JSX.Element {
    const alert = storyAlerts[insightType]
    return (
        <EditAlertModal
            isOpen
            alertId={alert.id}
            insightId={alert.insight.id}
            insightShortId={alert.insight.short_id}
            insightLogicProps={{
                dashboardItemId: alert.insight.short_id,
                cachedInsight: alert.insight,
            }}
            onEditSuccess={() => {}}
            onClose={() => {}}
            useAlertCheckPreview
        />
    )
}

type EditAlertVariant = StoryObj<AlertTypeStoryProps>

export const EditAlert: EditAlertVariant = {
    args: { insightType: 'trends' },
    argTypes: {
        insightType: {
            control: 'select',
            options: ['trends', 'funnel', 'hogql'],
        },
    },
    render: ({ insightType }) => <EditAlertStory insightType={insightType} />,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/alerts/:alert_id/': (request) => [
                    200,
                    alertsById[request.params.alert_id as string],
                ],
                '/api/projects/:team_id/hog_functions/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

interface CreateWizardStoryProps {
    insightType: StoryInsightType
}

const wizardCachedResults: Record<StoryInsightType, Record<string, unknown>> = {
    trends: {
        results: [
            {
                data: [4200000, 5100000, 4800000, 6700000, 7200000, 6100000, 8300000, 9400000],
                labels: ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00'],
            },
        ],
    },
    funnel: {
        results: [
            { name: 'Checkout started', count: 1000 },
            { name: 'Order completed', count: 350 },
        ],
    },
    hogql: {
        results: [
            ['2026-07-15 12:00:00', 850],
            ['2026-07-16 12:00:00', 1200],
        ],
        columns: ['recorded_at', 'queue_depth'],
        types: [
            ['recorded_at', 'DateTime'],
            ['queue_depth', 'UInt64'],
        ],
    },
}

function CreateWizardStory({ insightType }: CreateWizardStoryProps): JSX.Element {
    const selectedAlert = storyAlerts[insightType]
    const query = selectedAlert.insight.query
    if (!isInsightVizNode(query)) {
        throw new Error('Create wizard story requires an insight visualization query')
    }
    const insightLogicProps = {
        dashboardItemId: selectedAlert.insight.short_id,
        cachedInsight: selectedAlert.insight,
    }

    return (
        <BindLogic
            logic={dataNodeLogic}
            props={{
                key: insightVizDataNodeKey(insightLogicProps),
                query: query.source,
                cachedResults: wizardCachedResults[insightType],
                doNotLoad: true,
            }}
        >
            <EditAlertModal
                isOpen
                insightId={selectedAlert.insight.id}
                insightShortId={selectedAlert.insight.short_id}
                insightName={selectedAlert.insight.name}
                insightLogicProps={insightLogicProps}
                onEditSuccess={() => {}}
                onClose={() => {}}
            />
        </BindLogic>
    )
}

type CreateWizardVariant = StoryObj<CreateWizardStoryProps>

export const CreateWizard: CreateWizardVariant = {
    args: { insightType: 'trends' },
    argTypes: {
        insightType: {
            control: 'select',
            options: ['trends', 'funnel', 'hogql'],
        },
    },
    render: ({ insightType }) => <CreateWizardStory insightType={insightType} />,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_functions/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}
