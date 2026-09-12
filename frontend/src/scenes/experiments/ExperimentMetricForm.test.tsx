import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { useMocks } from '~/mocks/jest'
import {
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentRetentionMetric,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelConversionWindowTimeUnit } from '~/types'

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
    const metric: ExperimentRetentionMetric = {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.RETENTION,
        start_event: { kind: NodeKind.ExperimentExposureMetricSource },
        completion_event: { kind: NodeKind.EventsNode, event: 'returned' },
        retention_window_start: 1,
        retention_window_end: 7,
        retention_window_unit: FunnelConversionWindowTimeUnit.Day,
        start_handling: 'first_seen',
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/actions/': { results: [] },
                '/api/projects/:team/event_definitions/': { results: [] },
                '/api/projects/:team/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

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

    it('shows an unavailable exposure preview without tracking warnings or unused conversion controls', () => {
        render(<ExperimentMetricForm metric={metric} handleSetMetric={jest.fn()} filterTestAccounts={false} />)

        expect(screen.getByText(/Preview unavailable/)).toBeInTheDocument()
        expect(screen.queryByText('No recent activity')).not.toBeInTheDocument()
        expect(screen.queryByText('Conversion window limit')).not.toBeInTheDocument()
    })

    it('keeps the completion source when changing an exposure metric to a mean metric', () => {
        const handleSetMetric = jest.fn()
        render(<ExperimentMetricForm metric={metric} handleSetMetric={handleSetMetric} filterTestAccounts={false} />)

        fireEvent.click(screen.getByText('Mean'))

        expect(handleSetMetric).toHaveBeenCalledWith(
            expect.objectContaining({ metric_type: ExperimentMetricType.MEAN, source: metric.completion_event })
        )
    })
})
