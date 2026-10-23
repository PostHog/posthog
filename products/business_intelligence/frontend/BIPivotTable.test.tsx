import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DEFAULT_BI_CONFIG } from './biEditorTypes'
import { BIPivotTable } from './BIPivotTable'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'events' },
})

describe('BIPivotTable', () => {
    beforeEach(initKeaTests)
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('windows a large sparse pivot on both axes and inspects the last cell', () => {
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
            function (this: HTMLElement): number {
                return this.tagName === 'TR' ? 36 : 180
            }
        )
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
        const config = {
            ...DEFAULT_BI_CONFIG,
            chartType: ChartDisplayType.ActionsTable,
            rows: [field('region')],
            columns: [field('channel')],
            values: [
                { field: field('amount'), aggregation: 'sum' as const },
                { field: field('event'), aggregation: 'custom' as const, customExpression: 'argMax(event, timestamp)' },
            ],
        }
        const results = [
            ...Array.from({ length: 600 }, (_, index) => [`Region ${index}`, 'Channel 0', index, 'view']),
            ...Array.from({ length: 89 }, (_, index) => ['Region 0', `Channel ${index + 1}`, index + 1, 'view']),
            ['Region 599', 'Channel 89', 59989, 'purchase'],
        ]
        const onInspect = jest.fn()
        const { container } = render(
            <div style={{ height: 180 }}>
                <BIPivotTable
                    config={config}
                    columns={['bi_row_region', 'bi_column_channel', 'sum_amount', 'custom_event_2']}
                    results={results}
                    onInspect={onInspect}
                    embedded
                />
            </div>
        )
        const scroll = container.querySelector('.ScrollableShadows__inner')!
        expect(screen.getByText('Region 0')).toBeVisible()
        expect(screen.queryByText('Region 599')).not.toBeInTheDocument()
        expect(container.querySelectorAll('tbody td').length).toBeLessThan(250)

        fireEvent.scroll(scroll, { target: { scrollLeft: 181 * 192 - 800, scrollTop: 600 * 36 } })

        expect(screen.getByText('Region 599')).toBeVisible()
        expect(screen.queryByText('Region 0')).not.toBeInTheDocument()
        expect(screen.getByText('59989')).toBeVisible()
        const lastCell = screen.getByText('purchase')
        fireEvent.click(lastCell)
        expect(onInspect).toHaveBeenCalledWith({
            bi_row_region: 'Region 599',
            bi_column_channel: 'Channel 89',
            sum_amount: 59989,
            custom_event_2: 'purchase',
        })
        expect(container.querySelectorAll('tbody td').length).toBeLessThan(250)
    })
    it('keeps the last column reachable at the width limit and rejects wider pivots', () => {
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(180)
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            chartType: ChartDisplayType.ActionsTable,
            rows: [field('region')],
            columns: [field('channel')],
            values: [
                { field: field('amount'), aggregation: 'sum' },
                { field: field('cost'), aggregation: 'sum' },
            ],
        }
        const results = Array.from({ length: 5001 }, (_, index) => ['East', `Channel ${index}`, index, index + 10000])
        const props = { config, columns: ['bi_row_region', 'bi_column_channel', 'sum_amount', 'sum_cost_2'] }
        const { container, rerender } = render(<BIPivotTable {...props} results={results.slice(0, 5000)} />)
        const scroll = container.querySelector('.ScrollableShadows__inner')!
        fireEvent.scroll(scroll, { target: { scrollLeft: 10001 * 192 - 800 } })
        expect(screen.getByText('14999')).toBeVisible()
        expect(container.querySelectorAll('tbody td').length).toBeLessThan(30)

        rerender(<BIPivotTable {...props} results={results} />)
        expect(
            screen.getByText(
                'This pivot has more than 10,000 measure columns. Reduce the column dimensions or use Top N.'
            )
        ).toBeVisible()
        expect(container.querySelector('table')).not.toBeInTheDocument()
    })
})
