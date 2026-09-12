import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { ExperimentMetricType, type ExperimentRetentionMetric, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelConversionWindowTimeUnit } from '~/types'

import { MetricRecentActivity } from './MetricRecentActivity'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

describe('MetricRecentActivity', () => {
    const retentionMetric: ExperimentRetentionMetric = {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.RETENTION,
        start_event: { kind: NodeKind.EventsNode, event: 'signup' },
        completion_event: { kind: NodeKind.EventsNode, event: 'returned' },
        retention_window_start: 1,
        retention_window_end: 7,
        retention_window_unit: FunnelConversionWindowTimeUnit.Day,
        start_handling: 'first_seen',
    }

    beforeEach(() => {
        jest.mocked(performQuery).mockReset().mockResolvedValue({ results: [] })
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        ['a metric that starts at the exposure event', 'exposure-start', true],
        ['a metric whose preview query returns nothing', 'empty-response', false],
    ])('reports unavailable activity for %s', async (_case, uuid, startsAtExposure) => {
        const metric: ExperimentRetentionMetric = {
            ...retentionMetric,
            uuid,
            ...(startsAtExposure && { start_event: { kind: NodeKind.ExperimentExposureMetricSource } }),
        }

        render(<MetricRecentActivity metric={metric} filterTestAccounts={false} />)

        expect(await screen.findByText('Activity preview unavailable')).toBeInTheDocument()
        expect(screen.queryByText('0')).not.toBeInTheDocument()
    })

    it('still reports a resolved count of zero as zero', async () => {
        jest.mocked(performQuery).mockResolvedValue({ results: [{ aggregated_value: 0 }] })

        render(
            <MetricRecentActivity metric={{ ...retentionMetric, uuid: 'resolved-zero' }} filterTestAccounts={false} />
        )

        expect(await screen.findByText('0')).toBeInTheDocument()
        expect(screen.queryByText('Activity preview unavailable')).not.toBeInTheDocument()
    })
})
