import { fireEvent, render } from '@testing-library/react'

import { Legend, type LegendItem } from './Legend'

const ITEMS: LegendItem[] = [
    { key: 'new', label: 'New', color: '#22c55e' },
    { key: 'returning', label: 'Returning', color: '#3b82f6' },
    { key: 'dormant', label: 'Dormant', color: '#f97316' },
]

function rowsOf(container: HTMLElement): HTMLElement[] {
    return Array.from(container.firstChild!.childNodes) as HTMLElement[]
}

describe('Legend', () => {
    it('renders one row per item with the right label and swatch color', () => {
        const { container } = render(<Legend items={ITEMS} />)
        const swatches = Array.from(container.querySelectorAll<HTMLElement>('[aria-hidden="true"]'))
        expect(swatches.map((s) => s.style.backgroundColor).every(Boolean)).toBe(true)
        expect(swatches).toHaveLength(ITEMS.length)
        expect(rowsOf(container).map((r) => r.textContent)).toEqual(ITEMS.map((i) => i.label))
    })

    it('renders nothing when items is empty', () => {
        const { container } = render(<Legend items={[]} />)
        expect(container.firstChild).toBeNull()
    })

    it('uses flex-row + flex-wrap for horizontal and flex-col for vertical', () => {
        const h = render(<Legend items={ITEMS} dataAttr="h" />).container.querySelector('[data-attr="h"]')!
        const v = render(<Legend items={ITEMS} orientation="vertical" dataAttr="v" />).container.querySelector(
            '[data-attr="v"]'
        )!
        expect(h.className).toContain('flex-row')
        expect(h.className).toContain('flex-wrap')
        expect(v.className).toContain('flex-col')
        expect(v.className).not.toContain('flex-wrap')
    })

    it('renders items as spans by default and as buttons that fire onItemClick when set', () => {
        const onClick = jest.fn()
        const plain = render(<Legend items={ITEMS} />).container
        expect(plain.querySelectorAll('button')).toHaveLength(0)

        const clickable = render(<Legend items={ITEMS} onItemClick={onClick} />).container
        const buttons = clickable.querySelectorAll('button')
        expect(buttons).toHaveLength(ITEMS.length)
        fireEvent.click(buttons[1])
        expect(onClick).toHaveBeenCalledWith('returning')
    })

    it('wraps each row via renderItem while preserving the default node', () => {
        const onClick = jest.fn()
        const { container } = render(
            <Legend
                items={ITEMS}
                onItemClick={onClick}
                renderItem={(node, item) => <div data-attr={`wrap-${item.key}`}>{node}</div>}
            />
        )
        expect(container.querySelectorAll('[data-attr^="wrap-"]')).toHaveLength(ITEMS.length)
        const wrapped = container.querySelector('[data-attr="wrap-returning"] button')!
        fireEvent.click(wrapped)
        expect(onClick).toHaveBeenCalledWith('returning')
    })

    it('exposes the full name via a native title tooltip and truncates', () => {
        const long = 'Breakdown value with an extremely long name that would otherwise crush the plot'
        const { container } = render(<Legend items={[{ key: 'a', label: long, color: '#000' }]} />)
        const label = container.querySelector<HTMLElement>(`[title="${long}"]`)!
        expect(label.textContent).toBe(long)
        expect(label.className).toContain('truncate')
    })

    it('caps a crowded horizontal legend but leaves a lone series unclipped', () => {
        const long = 'Breakdown value with an extremely long name that would otherwise crush the plot'
        const crowded = render(
            <Legend
                items={[
                    { key: 'a', label: long, color: '#000' },
                    { key: 'b', label: 'Other', color: '#111' },
                ]}
            />
        ).container.querySelector<HTMLElement>(`[title="${long}"]`)!
        expect(crowded.style.maxWidth).toBe('180px')

        const lone = render(
            <Legend items={[{ key: 'a', label: long, color: '#000' }]} />
        ).container.querySelector<HTMLElement>(`[title="${long}"]`)!
        expect(lone.style.maxWidth).toBe('')
    })

    it('fills the slot and truncates for a vertical legend instead of a fixed cap', () => {
        const { container } = render(<Legend items={ITEMS} orientation="vertical" />)
        const label = container.querySelector<HTMLElement>(`[title="${ITEMS[0].label}"]`)!
        expect(label.className).toContain('truncate')
        expect(label.className).toContain('flex-1')
        expect(label.style.maxWidth).toBe('')
    })

    it('dims only rows whose key is in hiddenKeys', () => {
        const { container } = render(<Legend items={ITEMS} hiddenKeys={['returning']} />)
        const dimmedLabels = rowsOf(container)
            .filter((row) => row.className.includes('opacity-40'))
            .map((row) => row.textContent)
        expect(dimmedLabels).toEqual(['Returning'])
    })
})
