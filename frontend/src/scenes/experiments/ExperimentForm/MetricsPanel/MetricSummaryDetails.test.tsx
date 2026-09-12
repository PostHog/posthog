import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { ExperimentMetricType, ExperimentRetentionMetric, NodeKind } from '~/queries/schema/schema-general'
import { FunnelConversionWindowTimeUnit } from '~/types'

import { MetricConversionWindow } from './MetricConversionWindow'
import { MetricRecentActivity } from './MetricRecentActivity'

jest.mock('kea', () => ({ useValues: jest.fn() }))
jest.mock('./metricRecentActivityLogic', () => ({ metricRecentActivityLogic: jest.fn() }))

const metric: ExperimentRetentionMetric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.RETENTION,
    start_event: { kind: NodeKind.ExperimentExposureMetricSource },
    completion_event: { kind: NodeKind.EventsNode, event: 'returned' },
    retention_window_start: 1,
    retention_window_end: 7,
    retention_window_unit: FunnelConversionWindowTimeUnit.Day,
    start_handling: 'first_seen',
    conversion_window: 14,
    conversion_window_unit: FunnelConversionWindowTimeUnit.Day,
}

describe('exposure retention metric summary details', () => {
    afterEach(cleanup)

    it('hides the ignored conversion window', () => {
        render(<MetricConversionWindow metric={metric} />)

        expect(screen.queryByText(/Conversion window/)).not.toBeInTheDocument()
    })

    it('shows that recent activity is unavailable', () => {
        jest.mocked(useValues).mockReturnValue({ eventCount: null, eventCountLoading: false })

        render(<MetricRecentActivity metric={metric} filterTestAccounts={false} />)

        expect(screen.getByText('Activity preview unavailable')).toBeInTheDocument()
        expect(screen.queryByText('0')).not.toBeInTheDocument()
    })
})
