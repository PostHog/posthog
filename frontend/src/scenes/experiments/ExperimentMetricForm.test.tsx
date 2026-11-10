import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentWarehouseNativeExposureConfig,
    ExperimentWarehouseNativeMathType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExperimentMetricMathType, FunnelConversionWindowTimeUnit } from '~/types'

import { ExperimentMetricForm } from './ExperimentMetricForm'
import { getDefaultExperimentMetric } from './utils'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn().mockResolvedValue({ results: [] }),
}))

jest.mock('~/layout/scenes/components/SceneContent', () => ({
    SceneContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

jest.mock('scenes/insights/filters/ActionFilter/ActionFilter', () => ({
    SeriesActionFilter: ({ dataWarehousePopoverFields, dataWarehouseNodeKind, onChange }: Record<string, any>) => (
        <button
            data-attr="select-data-warehouse-step"
            onClick={() =>
                onChange([
                    {
                        kind: dataWarehouseNodeKind,
                        id: 'stripe_charges',
                        table_name: 'stripe_charges',
                        name: 'Stripe charges',
                        timestamp_field: 'created_at',
                        data_warehouse_join_key: 'customer_id',
                        events_join_key: 'distinct_id',
                    },
                ])
            }
        >
            {(dataWarehousePopoverFields ?? []).map(({ key }: { key: string }) => key).join(',')}
        </button>
    ),
}))

jest.mock('lib/monaco/CodeEditorResizable', () => ({
    CodeEditorResizeable: ({ value }: { value: string }) => <pre>{value}</pre>,
}))

describe('ExperimentMetricForm', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.EXPERIMENTS_QUANTILE_METRICS]: true })
    })

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

    it.each([
        [
            'an event property',
            { math_property: 'load_ms', math_property_type: 'numerical_event_properties' },
            'load_ms',
        ],
        ['the session duration', { math_property: '$session_duration' }, undefined],
        [
            'a session property',
            { math_property: '$session_pageview_count', math_property_type: 'session_properties' },
            undefined,
        ],
    ])('keeps only an event property when a mean metric of %s becomes a percentile', async (_, property, expected) => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'page_loaded',
                math: ExperimentMetricMathType.Avg,
                ...property,
            },
        }
        const handleSetMetric = jest.fn()

        const { container } = render(
            <ExperimentMetricForm metric={metric} handleSetMetric={handleSetMetric} filterTestAccounts={false} />
        )
        await userEvent.click(container.querySelector(`input[value="${ExperimentMetricType.QUANTILE}"]`)!)

        expect(handleSetMetric).toHaveBeenCalledWith(
            expect.objectContaining({
                metric_type: ExperimentMetricType.QUANTILE,
                source: expect.objectContaining({
                    event: 'page_loaded',
                    math: undefined,
                    math_property: expected,
                    math_property_type: undefined,
                }),
            })
        )
    })

    it.each([
        ['offered', true, ExperimentMetricType.MEAN, true],
        ['hidden', false, ExperimentMetricType.MEAN, false],
        ['kept', false, ExperimentMetricType.QUANTILE, true],
    ])('the percentile type is %s when the flag is %s and the metric is %s', (_, flagEnabled, metricType, shown) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.EXPERIMENTS_QUANTILE_METRICS]: flagEnabled })

        const { container } = render(
            <ExperimentMetricForm
                metric={getDefaultExperimentMetric(metricType)}
                handleSetMetric={jest.fn()}
                filterTestAccounts={false}
            />
        )

        expect(!!container.querySelector('[data-attr="experiment-metric-type-quantile"]')).toBe(shown)
    })

    it('edits a warehouse-native metric and keeps every source warehouse-native when its type changes', async () => {
        const exposure: ExperimentWarehouseNativeExposureConfig = {
            kind: NodeKind.ExperimentWarehouseNativeExposureConfig,
            connection_id: 'connection-1',
            unit: { unit_type: 'customer', id_namespace: 'billing_customer_id' },
            query: 'SELECT customer_id AS entity_id, variant, exposed_at AS timestamp FROM billing.exposures',
        }
        const source = {
            kind: NodeKind.ExperimentWarehouseNativeNode as const,
            connection_id: exposure.connection_id,
            unit: exposure.unit,
            query: 'SELECT customer_id AS entity_id, paid_at AS timestamp FROM billing.payments',
            math: ExperimentWarehouseNativeMathType.TotalCount,
        }
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            uuid: 'metric-1',
            metric_type: ExperimentMetricType.MEAN,
            source,
        }
        const handleSetMetric = jest.fn()

        const { container } = render(
            <ExperimentMetricForm
                metric={metric}
                handleSetMetric={handleSetMetric}
                filterTestAccounts={false}
                exposureCriteria={{ exposure_config: exposure }}
            />
        )

        expect(screen.getByText(source.query)).toBeInTheDocument()
        expect(container.querySelector('[data-attr="experiment-metric-type-funnel"]')).toBeDisabled()

        // a click on the selected data source must not reset the metric
        await userEvent.click(
            container.querySelector('[data-attr="experiment-metric-data-source-warehouse-native"]') as HTMLElement
        )
        expect(handleSetMetric).not.toHaveBeenCalled()

        await userEvent.click(container.querySelector('[data-attr="experiment-metric-type-ratio"]') as HTMLElement)

        expect(handleSetMetric).toHaveBeenCalledWith(
            expect.objectContaining({
                uuid: 'metric-1',
                metric_type: ExperimentMetricType.RATIO,
                numerator: source,
                denominator: { ...source, query: '' },
            })
        )
    })
})
