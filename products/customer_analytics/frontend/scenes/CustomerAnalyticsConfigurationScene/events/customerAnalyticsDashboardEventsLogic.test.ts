import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ActionsNode, CustomerAnalyticsConfig, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

import { customerAnalyticsConfigLogic } from 'products/customer_analytics/frontend/customerAnalyticsConfigLogic'

import { customerAnalyticsDashboardEventsLogic } from './customerAnalyticsDashboardEventsLogic'

const pageview: EventsNode = { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }
const paid: ActionsNode = { kind: NodeKind.ActionsNode, id: 7, name: 'Paid', custom_name: 'Payments' }
const browserFilter = {
    key: '$browser',
    value: ['Chrome'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event as const,
}

describe('customerAnalyticsDashboardEventsLogic', () => {
    let logic: ReturnType<typeof customerAnalyticsDashboardEventsLogic.build>

    beforeEach(() => {
        useMocks({ patch: { '/api/projects/:id': () => [200, MOCK_DEFAULT_TEAM] } })
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: {
                ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                activity_event: {},
                signup_event: pageview,
            } as CustomerAnalyticsConfig,
        })
        logic = customerAnalyticsDashboardEventsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('offers an event the config leaves out as a button rather than an empty picker', () => {
        expectLogic(logic).toMatchValues({
            activityEventSeries: null,
            signupEventSeries: [{ ...pageview, custom_name: 'Signups' }],
        })
    })

    it('saves only the edited events, as config nodes without math', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActivityEventSelection([
                { ...pageview, math: BaseMathType.UniqueUsers, properties: [browserFilter] },
            ])
            logic.actions.setPaymentEventSelection([paid])
            logic.actions.saveEvents()
        }).toDispatchActions([
            customerAnalyticsConfigLogic.actionCreators.updateEvents({
                activity_event: { ...pageview, properties: [browserFilter] },
                payment_event: paid,
            }),
        ])
    })
})
