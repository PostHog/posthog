import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

import { ExperimentMetricForm } from './ExperimentMetricForm'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn().mockResolvedValue({ results: [] }),
}))

jest.mock('~/layout/scenes/components/SceneContent', () => ({
    SceneContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

jest.mock('scenes/insights/filters/ActionFilter/ActionFilter', () => ({
    ActionFilter: ({ dataWarehousePopoverFields, setFilters }: Record<string, any>) => (
        <button
            data-attr="select-data-warehouse-step"
            onClick={() =>
                setFilters({
                    actions: [],
                    events: [],
                    data_warehouse: [
                        {
                            id: 'stripe_charges',
                            name: 'Stripe charges',
                            timestamp_field: 'created_at',
                            data_warehouse_join_key: 'customer_id',
                            events_join_key: 'distinct_id',
                            order: 0,
                        },
                    ],
                })
            }
        >
            {dataWarehousePopoverFields.map(({ key }: { key: string }) => key).join(',')}
        </button>
    ),
}))

describe('ExperimentMetricForm', () => {
    it('updates a funnel metric from the data warehouse popover fields', async () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.FUNNEL,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }
        const handleSetMetric = jest.fn()

        render(
            <ExperimentMetricForm
                metric={metric}
                isSharedMetric
                handleSetMetric={handleSetMetric}
                filterTestAccounts={false}
            />
        )

        const selectStep = screen.getByTestId('select-data-warehouse-step')
        expect(selectStep.textContent).toBe('timestamp_field,data_warehouse_join_key,events_join_key')

        await userEvent.click(selectStep)

        expect(handleSetMetric).toHaveBeenCalledWith({
            ...metric,
            series: [
                expect.objectContaining({
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'stripe_charges',
                    timestamp_field: 'created_at',
                    data_warehouse_join_key: 'customer_id',
                    events_join_key: 'distinct_id',
                }),
            ],
        })
    })
})
