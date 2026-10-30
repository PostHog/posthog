import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { execHog } from 'lib/hog'

import { conditionalFormattingColor } from '~/queries/nodes/DataVisualization/conditionalFormatting'
import { ColumnScalar } from '~/queries/nodes/DataVisualization/types'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ConditionalFormattingRule } from '~/queries/schema/schema-general'
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

    it.each(['rows', 'columns'] as const)(
        'places measures on %s without row dimensions and preserves drill-down',
        (shelf) => {
            jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(400)
            jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
            const config: BIConfig = {
                ...DEFAULT_BI_CONFIG,
                chartType: ChartDisplayType.ActionsTable,
                rows: [],
                columns: [field('channel')],
                values: [
                    {
                        field: field('amount'),
                        aggregation: 'sum',
                        shelf,
                        display: { label: 'Revenue' },
                        formatting: { prefix: '$' },
                    },
                    { field: field('orders'), aggregation: 'count', shelf, display: { label: 'Orders' } },
                ],
            }
            const onInspect = jest.fn()
            const { container } = render(
                <BIPivotTable
                    config={config}
                    columns={['bi_column_channel', 'sum_amount', 'count_orders_2']}
                    results={[
                        [null, 12, 3],
                        ['Search', 8, 2],
                    ]}
                    onInspect={onInspect}
                    cellBackground={(_, column) => (column === 'sum_amount' ? '#FFADAD' : undefined)}
                />
            )
            const body = container.querySelector('tbody')!
            expect(
                Array.from(body.querySelectorAll('tr')).map((row) =>
                    Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent)
                )
            ).toEqual(
                shelf === 'rows'
                    ? [
                          ['Revenue', '$12', '$8'],
                          ['Orders', '3', '2'],
                      ]
                    : [['', '$12', '3', '$8', '2']]
            )
            expect(
                Array.from(body.querySelectorAll<HTMLElement>('td')).filter((cell) => cell.style.backgroundColor)
            ).toHaveLength(2)
            fireEvent.click(screen.getByText('$12'))
            expect(onInspect).toHaveBeenCalledWith({ bi_column_channel: null, sum_amount: 12, count_orders_2: 3 })
        }
    )

    it.each<[boolean, string | number, string | number, ColumnScalar]>([
        [false, 10, 20, 'INTEGER'],
        [true, 10, 20, 'INTEGER'],
        [false, '10', '20', 'INTEGER'],
        [true, '10', '20', 'INTEGER'],
        [false, '2026-01-10', '2026-01-20', 'DATE'],
        [false, '2026-01-10T12:00:00Z', '2026-01-20T12:00:00Z', 'DATETIME'],
    ])(
        'formats raw measure values across pivot columns and updates rules, dark=%s, first=%s, second=%s, type=%s',
        (dark, first, second, type) => {
            jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(400)
            jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
            const config: BIConfig = {
                ...DEFAULT_BI_CONFIG,
                chartType: ChartDisplayType.ActionsTable,
                rows: [field('region')],
                columns: [field('channel')],
                values: [{ field: field('amount'), aggregation: 'sum', formatting: { style: 'number', prefix: '$' } }],
            }
            const rule: ConditionalFormattingRule = {
                id: 'equals',
                templateId: 'equals',
                columnName: 'sum_amount',
                input: String(first),
                color: '#FFADAD',
                colorMode: 'light',
                bytecode: ['_H', 1, 32, 'input', 1, 1, 32, 'value', 1, 1, 11, 38],
            }
            const props = {
                config,
                columns: ['bi_row_region', 'bi_column_channel', 'sum_amount'],
                results: [
                    ['East', 'Email', first],
                    ['East', 'Search', second],
                    ['West', 'Search', first],
                ],
            }
            const background = (record: Record<string, unknown>, column: string): string | undefined =>
                conditionalFormattingColor([rule], execHog, column, type, record[column], dark)
            const { container, rerender } = render(<BIPivotTable {...props} cellBackground={background} />)
            const coloredCells = (): HTMLElement[] =>
                Array.from(container.querySelectorAll<HTMLElement>('tbody td')).filter(
                    (cell) => !!cell.style.backgroundColor
                )
            expect(coloredCells()).toHaveLength(2)
            expect(
                coloredCells().every((cell) => cell.textContent === `${type === 'INTEGER' ? '$' : ''}${first}`)
            ).toBe(true)
            const firstColor = coloredCells()[0].style.backgroundColor
            rule.input = String(second)
            rerender(<BIPivotTable {...props} cellBackground={background} />)
            expect(coloredCells()).toHaveLength(1)
            expect(coloredCells()[0]).toHaveTextContent(`${type === 'INTEGER' ? '$' : ''}${second}`)
            expect(coloredCells()[0].style.backgroundColor).toBe(firstColor)
            rerender(<BIPivotTable {...props} cellBackground={() => undefined} />)
            expect(coloredCells()).toHaveLength(0)
        }
    )

    it.each(['rows', 'columns'] as const)(
        'windows a sparse pivot with measures on %s and inspects the last cell',
        (shelf) => {
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
                    { field: field('amount'), aggregation: 'sum' as const, shelf },
                    {
                        field: field('event'),
                        aggregation: 'custom' as const,
                        shelf,
                        customExpression: 'argMax(event, timestamp)',
                    },
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
            expect(screen.getAllByText('Region 0')[0]).toBeVisible()
            expect(screen.queryByText('Region 599')).not.toBeInTheDocument()
            expect(container.querySelectorAll('tbody td').length).toBeLessThan(250)

            fireEvent.scroll(scroll, {
                target: {
                    scrollLeft: (shelf === 'rows' ? 91 : 181) * 192 - 800,
                    scrollTop: 600 * (shelf === 'rows' ? 2 : 1) * 36,
                },
            })

            expect(screen.getAllByText('Region 599')[0]).toBeVisible()
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
        }
    )
    it('preserves vertical scroll when collapsing and expanding a column hierarchy', () => {
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
            function (this: HTMLElement): number {
                return this.tagName === 'TR' ? 36 : 180
            }
        )
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            chartType: ChartDisplayType.ActionsTable,
            rows: [field('region')],
            columns: [field('year'), field('quarter')],
            values: [{ field: field('amount'), aggregation: 'sum', shelf: 'rows' }],
        }
        const { container } = render(
            <BIPivotTable
                config={config}
                columns={['bi_row_region', 'bi_columns', 'sum_amount']}
                results={Array.from({ length: 600 }, (_, index) => [
                    `Region ${index}`,
                    JSON.stringify(['2026', 'Q1']),
                    index,
                ])}
            />
        )
        const scroll = container.querySelector<HTMLElement>('.ScrollableShadows__inner')!
        scroll.scrollTo = (options?: ScrollToOptions | number): void => {
            if (typeof options === 'object' && options.top !== undefined) {
                scroll.scrollTop = options.top
            }
        }
        fireEvent.scroll(scroll, { target: { scrollTop: 300 * 36 } })
        for (const action of ['Collapse', 'Expand']) {
            fireEvent.click(screen.getByLabelText(`${action} 2026`))
            expect(scroll.scrollTop).toBe(300 * 36)
        }
    })

    it.each(['rows', 'columns'] as const)(
        'keeps the last cell reachable at the %s limit and rejects larger pivots',
        (shelf) => {
            jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
                function (this: HTMLElement): number {
                    return this.tagName === 'TR' ? 36 : 180
                }
            )
            jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
            const config: BIConfig = {
                ...DEFAULT_BI_CONFIG,
                chartType: ChartDisplayType.ActionsTable,
                rows: [field('region')],
                columns: [field('channel')],
                values: [
                    { field: field('amount'), aggregation: 'sum', shelf },
                    { field: field('cost'), aggregation: 'sum', shelf },
                ],
            }
            const memberLimit = shelf === 'rows' ? 50000 : 5000
            const results = Array.from({ length: memberLimit + 1 }, (_, index) => [
                shelf === 'rows' ? `Region ${index}` : 'East',
                shelf === 'columns' ? `Channel ${index}` : 'Email',
                index,
                index + 10000,
            ])
            const props = { config, columns: ['bi_row_region', 'bi_column_channel', 'sum_amount', 'sum_cost_2'] }
            const { container, rerender } = render(<BIPivotTable {...props} results={results.slice(0, memberLimit)} />)
            const scroll = container.querySelector('.ScrollableShadows__inner')!
            fireEvent.scroll(scroll, {
                target: shelf === 'rows' ? { scrollTop: 100000 * 36 } : { scrollLeft: 10001 * 192 - 800 },
            })
            expect(screen.getByText(String(memberLimit + 9999))).toBeVisible()
            expect(container.querySelectorAll('tbody td').length).toBeLessThan(100)

            rerender(<BIPivotTable {...props} results={results} />)
            expect(
                screen.getByText(
                    shelf === 'rows'
                        ? 'This pivot has more than 100,000 rows. Reduce the row dimensions or measures, or use Top N.'
                        : 'This pivot has more than 10,000 measure columns. Reduce the column dimensions or use Top N.'
                )
            ).toBeVisible()
            expect(container.querySelector('table')).not.toBeInTheDocument()
        }
    )
})
