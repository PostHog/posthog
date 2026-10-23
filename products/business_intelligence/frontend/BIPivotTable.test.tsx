import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { BIField } from '~/queries/schema/schema-business-intelligence'
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
            values: [{ field: field('amount'), aggregation: 'sum' as const }],
        }
        const results = [
            ...Array.from({ length: 600 }, (_, index) => [`Region ${index}`, 'Channel 0', index]),
            ...Array.from({ length: 89 }, (_, index) => ['Region 0', `Channel ${index + 1}`, index + 1]),
            ['Region 599', 'Channel 89', 59989],
        ]
        const onInspect = jest.fn()
        const { container } = render(
            <div style={{ height: 180 }}>
                <BIPivotTable
                    config={config}
                    columns={['bi_row_region', 'bi_column_channel', 'sum_amount']}
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

        fireEvent.scroll(scroll, { target: { scrollLeft: 91 * 192 - 800, scrollTop: 600 * 36 } })

        expect(screen.getByText('Region 599')).toBeVisible()
        expect(screen.queryByText('Region 0')).not.toBeInTheDocument()
        const lastCell = screen.getByText('59989')
        fireEvent.click(lastCell)
        expect(onInspect).toHaveBeenCalledWith({
            bi_row_region: 'Region 599',
            bi_column_channel: 'Channel 89',
            sum_amount: 59989,
        })
        expect(container.querySelectorAll('tbody td').length).toBeLessThan(250)
    })
})
