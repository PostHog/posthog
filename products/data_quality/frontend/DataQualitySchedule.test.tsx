import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { DataQualitySchedule } from './DataQualitySchedule'
import { dataCatalogMetricsChecksScheduleRetrieve } from './generated/api'

jest.mock('./generated/api', () => ({
    dataCatalogMetricsChecksScheduleRetrieve: jest.fn(),
    dataCatalogMetricsChecksSchedulePartialUpdate: jest.fn(),
}))

describe('DataQualitySchedule', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-08T12:00:00Z'))
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    it('shows an elapsed next run as due now', async () => {
        ;(dataCatalogMetricsChecksScheduleRetrieve as jest.Mock).mockResolvedValue({
            id: 'schedule-1',
            enabled: true,
            interval: '1hour',
            next_run_at: '2026-09-08T11:00:00Z',
            last_run_at: null,
            last_suite_run: null,
        })

        render(<DataQualitySchedule metricId="metric-1" />)

        const dueNow = await screen.findByText('due now')
        expect(dueNow).toBeInTheDocument()
        expect(screen.queryByText(/ago$/)).not.toBeInTheDocument()
    })
})
