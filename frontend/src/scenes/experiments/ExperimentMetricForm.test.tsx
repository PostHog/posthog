import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricMathType, FunnelConversionWindowTimeUnit } from '~/types'

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

    it('toggles a retention start between a custom event and the experiment exposure', async () => {
        const startEvent = {
            kind: NodeKind.EventsNode,
            event: 'signup',
            name: 'signup',
            math: ExperimentMetricMathType.TotalCount,
        } as const
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.RETENTION,
            start_event: startEvent,
            completion_event: { kind: NodeKind.EventsNode, event: '$pageview' },
            retention_window_start: 1,
            retention_window_end: 7,
            retention_window_unit: FunnelConversionWindowTimeUnit.Day,
            start_handling: 'last_seen',
            conversion_window: 14,
            conversion_window_unit: FunnelConversionWindowTimeUnit.Day,
        }
        const handleSetMetric = jest.fn()

        const { container, rerender } = render(
            <ExperimentMetricForm metric={metric} handleSetMetric={handleSetMetric} filterTestAccounts={false} />
        )
        const form = within(container as HTMLElement)

        expect(form.getByText('When users have multiple start events')).toBeInTheDocument()
        expect(form.getByText('Conversion window limit')).toBeInTheDocument()

        // switching to exposure clears the settings the backend rejects for an exposure start
        await userEvent.click(form.getByText('Experiment exposure'))
        expect(handleSetMetric).toHaveBeenCalledWith({
            ...metric,
            start_event: { kind: NodeKind.ExperimentExposureNode },
            start_handling: 'first_seen',
            conversion_window: undefined,
            conversion_window_unit: undefined,
        })

        const exposureMetric = handleSetMetric.mock.calls[0][0]
        rerender(
            <ExperimentMetricForm
                metric={exposureMetric}
                handleSetMetric={handleSetMetric}
                filterTestAccounts={false}
            />
        )

        expect(form.queryByText('When users have multiple start events')).not.toBeInTheDocument()
        expect(form.queryByText('Conversion window limit')).not.toBeInTheDocument()

        // switching back restores the custom start event and its cleared settings
        await userEvent.click(form.getByText('Custom event'))
        expect(handleSetMetric).toHaveBeenLastCalledWith({
            ...exposureMetric,
            start_event: startEvent,
            start_handling: 'last_seen',
            conversion_window: 14,
            conversion_window_unit: FunnelConversionWindowTimeUnit.Day,
        })
    })
})
