import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { DotGlyph } from './DotGlyph'
import { DotMatrix } from './DotMatrix'

const data = [{ location: 'North', period: 'Morning', check: 'Safety', total: 12 }]
const fields = { row: 'location', column: 'period', series: 'check', value: 'total' } as const

describe('DotMatrix', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('highlights a hovered legend product without changing the selection or removing glyph slots', () => {
        const selected = jest.fn()
        const { container } = render(
            <DotMatrix
                data={[...data, { location: 'North', period: 'Morning', check: 'Quality', total: 5 }]}
                fields={fields}
                selectedSeries={['Safety']}
                onSelectedSeriesChange={selected}
            />
        )
        const safety = screen.getByText('Safety')
        const glyph = container.querySelector('.DotGlyph')!
        fireEvent.mouseEnter(safety)
        expect(glyph.querySelector('[data-series="Quality"]')?.getAttribute('opacity')).toBe('0.25')
        expect(glyph.querySelector('[data-series="Safety"]')?.getAttribute('opacity')).toBe('1')
        expect(glyph.querySelectorAll('circle')).toHaveLength(5)
        fireEvent.mouseLeave(safety)
        expect(glyph.querySelector('[data-series="Quality"]')?.getAttribute('opacity')).toBe('1')
        expect(selected).not.toHaveBeenCalled()
    })

    it('scales use-case glyphs to a 13px pitch while retaining all rings', () => {
        const { container } = render(
            <DotGlyph series={[{ key: 'a' }]} values={{ a: 10 }} label="Example" columnsPerGroup={5} cellPitch={13} />
        )
        const glyph = container.querySelector('svg')!
        expect(glyph.getAttribute('width')).toBe('65')
        expect(glyph.getAttribute('height')).toBe('13')
        expect(glyph.querySelectorAll('circle')).toHaveLength(3)
    })

    it('exposes passive custom cell details on focus and dismisses them with Escape', async () => {
        const { container } = render(
            <DotMatrix
                data={data}
                fields={fields}
                renderCell={() => <span>Custom count</span>}
                renderTooltip={() => <span>Inspection details</span>}
            />
        )
        const cell = container.querySelector<HTMLElement>('.DotMatrix__cell')!
        expect(cell.tabIndex).toBe(0)
        expect(cell.dataset.rowKey).toBe('North')
        expect(cell.dataset.columnKey).toBe('Morning')
        fireEvent.focus(cell)
        expect(await screen.findByText('Inspection details')).toBeTruthy()
        fireEvent.keyDown(document, { key: 'Escape' })
        await waitFor(() => expect(screen.queryByText('Inspection details')).toBeNull())
    })

    it('leaves focus to custom child controls when the cell has no outer tooltip', () => {
        const { container } = render(
            <DotMatrix
                data={data}
                fields={fields}
                renderCell={() => <button>Inspect</button>}
                renderTooltip={() => null}
            />
        )
        expect(container.querySelector<HTMLElement>('.DotMatrix__cell')!.tabIndex).toBe(-1)
        expect(screen.getByText('Inspect').tabIndex).toBe(0)
    })

    it.each([
        { thresholds: undefined, circles: 3, labels: ['1+', '5+', '10+'] },
        { thresholds: [1], circles: 1, labels: ['1+'] },
        { thresholds: [], circles: 0, labels: [] },
    ])(
        'uses the same configured threshold levels in the glyph and key: $thresholds',
        ({ thresholds, circles, labels }) => {
            const { container } = render(<DotMatrix data={data} fields={fields} sizeThresholds={thresholds} />)
            expect(container.querySelectorAll('.DotGlyph circle').length).toBe(circles)
            expect(
                Array.from(container.querySelectorAll('.DotMatrix__size-key b'), (item) => item.textContent)
            ).toEqual(labels)
        }
    )

    it('keeps every series dot visible when one series is selected', () => {
        const { container } = render(
            <DotMatrix
                data={[...data, { location: 'North', period: 'Morning', check: 'Fire', total: 4 }]}
                fields={fields}
                selectedSeries={['Fire']}
            />
        )
        expect(container.querySelector('.DotGlyph')?.getAttribute('aria-label')).toBe(
            'North, Morning: Safety 12, Fire 4'
        )
    })

    it('mounts only one page of rows when a page size is set', () => {
        const { container } = render(
            <DotMatrix
                data={[...data, { location: 'South', period: 'Morning', check: 'Safety', total: 3 }]}
                fields={fields}
                pageSize={1}
            />
        )
        expect(container.querySelectorAll('.DotGlyph').length).toBe(1)
    })

    it('matches the count legend to colors when caller bins are unordered', () => {
        const { container } = render(
            <DotMatrix
                data={data}
                fields={fields}
                mode="count"
                countOf="value"
                countScale={[
                    { min: 10, color: 'red' },
                    { min: 1, color: 'green' },
                    { min: 5, color: 'blue' },
                ]}
            />
        )
        expect(container.querySelector('.CountCell rect')?.getAttribute('fill')).toBe('red')
        expect(
            Array.from(container.querySelectorAll('.DotMatrix__count-key .DotMatrix__key-item'), (item) => ({
                label: item.textContent,
                color: item.querySelector('rect')?.getAttribute('fill'),
            }))
        ).toEqual([
            { label: '1-4', color: 'green' },
            { label: '5-9', color: 'blue' },
            { label: '10+', color: 'red' },
        ])
    })
    it.each([
        { groups: [], expected: ['var(--data-color-1)', 'var(--data-color-2)'] },
        { groups: [{ key: 'checks', label: 'Checks', color: 'blue' }], expected: ['blue', 'blue'] },
    ])(
        'uses identical series colors in standalone glyphs, matrix cells, and legends: $groups',
        ({ groups, expected }) => {
            const series = [
                { key: 'Safety', group: 'checks' },
                { key: 'Quality', group: 'checks' },
            ]
            const { container } = render(
                <>
                    <DotGlyph series={series} values={{ Safety: 1, Quality: 1 }} groups={groups} label="Standalone" />
                    <DotMatrix
                        data={[
                            ...data.map((item) => ({ ...item, total: 1 })),
                            { ...data[0], check: 'Quality', total: 1 },
                        ]}
                        fields={fields}
                        series={series}
                        groups={groups}
                    />
                </>
            )
            for (const glyph of container.querySelectorAll('.DotGlyph')) {
                expect(Array.from(glyph.querySelectorAll('circle'), (circle) => circle.getAttribute('fill'))).toEqual(
                    expected
                )
            }
            expect(
                Array.from(container.querySelectorAll('.DotMatrix__legend-item circle'), (circle) =>
                    circle.getAttribute('fill')
                )
            ).toEqual(expected)
        }
    )

    it('passes the mapped cell to a click handler and describes its selected count', () => {
        const onCellClick = jest.fn()
        const aggregateSelection = jest.fn(() => 7)
        render(
            <DotMatrix
                data={data}
                fields={fields}
                mode="count"
                selectedSeries={['Safety']}
                aggregateSelection={aggregateSelection}
                onCellClick={onCellClick}
            />
        )
        fireEvent.click(screen.getByLabelText('North, Morning: 7', { selector: 'button' }))
        expect(onCellClick).toHaveBeenCalledWith({
            rowKey: 'North',
            columnKey: 'Morning',
            values: { Safety: 12 },
            data,
        })
        expect(aggregateSelection).toHaveBeenCalledWith(onCellClick.mock.calls[0][0], ['Safety'])
    })
    it('renders the same series in each explicit group and uses the requested columns', () => {
        const { container } = render(
            <DotMatrix
                data={data}
                fields={fields}
                groups={[
                    { key: 'one', label: 'One', items: ['Safety'] },
                    { key: 'two', label: 'Two', items: ['Safety'] },
                ]}
                columnsPerGroup={3}
                legend={false}
            />
        )
        const glyph = container.querySelector('.DotGlyph')!
        expect(glyph.getAttribute('width')).toBe('51')
        expect(glyph.getAttribute('height')).toBe('34')
        expect(glyph.querySelectorAll('circle').length).toBe(6)
    })

    it('marks first use on the matching product without hiding the other dots', () => {
        const { container } = render(
            <DotMatrix
                data={[...data, { location: 'North', period: 'Morning', check: 'Fire', total: 1 }]}
                fields={fields}
                firstUseSeries={() => ['Safety']}
                legend={false}
            />
        )
        expect(container.querySelectorAll('.DotGlyph polygon').length).toBe(1)
        expect(container.querySelectorAll('.DotGlyph circle').length).toBe(3)
    })
    it('keeps implicit series groups on separate glyph rows', () => {
        const { container } = render(
            <DotGlyph
                series={[
                    { key: 'one', group: 'a' },
                    { key: 'two', group: 'b' },
                ]}
                values={{ one: 1, two: 1 }}
                label="Groups"
            />
        )
        expect(container.querySelector('.DotGlyph')?.getAttribute('height')).toBe('34')
    })
})
