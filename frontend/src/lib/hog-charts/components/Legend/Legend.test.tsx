import { fireEvent, render } from '@testing-library/react'

import { Legend, type LegendItem } from './Legend'

const ITEMS: LegendItem[] = [
    { key: 'new', label: 'New', color: '#22c55e' },
    { key: 'returning', label: 'Returning', color: '#3b82f6' },
    { key: 'dormant', label: 'Dormant', color: '#f97316' },
]

function rowsOf(container: HTMLElement): HTMLElement[] {
    return Array.from(container.querySelectorAll<HTMLElement>('[data-attr="hog-chart-legend-item"]'))
}

function swatchOf(row: HTMLElement): HTMLElement {
    return row.querySelector<HTMLElement>('[aria-hidden="true"]')!
}

describe('Legend', () => {
    it('renders one row per item with the right label and swatch color', () => {
        const { container } = render(<Legend items={ITEMS} />)
        const rows = rowsOf(container)
        expect(rows).toHaveLength(ITEMS.length)
        expect(rows.map((r) => r.textContent)).toEqual(ITEMS.map((i) => i.label))
        // rgb form because jsdom normalizes inline color values
        expect(rows.map((r) => swatchOf(r).style.backgroundColor)).toEqual([
            'rgb(34, 197, 94)',
            'rgb(59, 130, 246)',
            'rgb(249, 115, 22)',
        ])
    })

    it('emits the intrinsic data-attr by default and each row exposes its key', () => {
        const { container } = render(<Legend items={ITEMS} />)
        expect(container.querySelector('[data-attr="hog-chart-legend"]')).not.toBeNull()
        expect(rowsOf(container).map((r) => r.dataset.key)).toEqual(['new', 'returning', 'dormant'])
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

    it.each([
        ['new', false],
        ['returning', true],
        ['dormant', false],
    ] as const)('hiddenKeys dims %s -> dimmed=%s', (key, dimmed) => {
        const { container } = render(<Legend items={ITEMS} hiddenKeys={['returning']} />)
        const row = container.querySelector<HTMLElement>(`[data-key="${key}"]`)!
        expect(row.className.includes('opacity-40')).toBe(dimmed)
    })
})
