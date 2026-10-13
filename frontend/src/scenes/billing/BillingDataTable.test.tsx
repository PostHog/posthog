import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { BillingSeriesType } from './BillingChart'
import { BillingDataTable } from './BillingDataTable'
import { BILLING_TABLE_PAGE_SIZE } from './constants'

const DATES = ['2026-01-01', '2026-01-02']

const seriesOf = (count: number): BillingSeriesType[] =>
    Array.from({ length: count }, (_, id) => ({
        id,
        label: `Project ${id}`,
        data: [id, id * 2],
        dates: DATES,
    }))

const renderTable = (series: BillingSeriesType[]): ReturnType<typeof render> =>
    render(
        <BillingDataTable
            series={series}
            dates={DATES}
            hiddenSeries={[]}
            toggleSeries={jest.fn()}
            toggleAllSeries={jest.fn()}
        />
    )

const bodyRows = (container: HTMLElement): number => container.querySelectorAll('tbody tr').length

describe('BillingDataTable', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders one page of rows rather than every series', () => {
        const { container } = renderTable(seriesOf(BILLING_TABLE_PAGE_SIZE * 3))

        expect(bodyRows(container)).toBe(BILLING_TABLE_PAGE_SIZE)
    })

    it('shows no pagination control when everything fits on one page', () => {
        const { container } = renderTable(seriesOf(5))

        expect(bodyRows(container)).toBe(5)
        expect(container.querySelector('.PaginationControl')).toBeNull()
    })

    it('sorts by total descending by default', () => {
        // The default sort is by total, so the largest series leads.
        renderTable(seriesOf(4))

        const labels = screen.getAllByText(/^Project \d+$/).map((el) => el.textContent)
        expect(labels).toEqual(['Project 3', 'Project 2', 'Project 1', 'Project 0'])
    })

    it('totals each series across the range', () => {
        renderTable([{ id: 7, label: 'Project 7', data: [10, 32], dates: DATES }])

        expect(screen.getByText('42')).toBeTruthy()
    })
})
