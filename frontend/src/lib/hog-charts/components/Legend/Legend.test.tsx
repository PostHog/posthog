import { fireEvent, render } from '@testing-library/react'
import fs from 'fs'
import path from 'path'

import { Legend, type LegendItem } from './Legend'

const ITEMS: LegendItem[] = [
    { key: 'new', label: 'New', color: '#22c55e' },
    { key: 'returning', label: 'Returning', color: '#3b82f6' },
    { key: 'resurrecting', label: 'Resurrecting', color: '#a855f7' },
    { key: 'dormant', label: 'Dormant', color: '#f97316' },
]

function hexToRgb(hex: string): string {
    const clean = hex.replace('#', '')
    const r = parseInt(clean.slice(0, 2), 16)
    const g = parseInt(clean.slice(2, 4), 16)
    const b = parseInt(clean.slice(4, 6), 16)
    return `rgb(${r}, ${g}, ${b})`
}

describe('Legend', () => {
    it('renders one row per item with the correct label text', () => {
        const { getByText } = render(<Legend items={ITEMS} />)
        const found = ITEMS.map((item) => getByText(item.label).textContent)
        expect(found).toEqual(ITEMS.map((i) => i.label))
    })

    it.each(ITEMS.map((item, index) => [item.key, index, item.color]))(
        "swatch for %s has inline background-color matching the item's color",
        (_key, index, color) => {
            const { container } = render(<Legend items={ITEMS} />)
            const swatches = container.querySelectorAll<HTMLElement>('[aria-hidden="true"]')
            expect(swatches[index as number].style.backgroundColor).toBe(hexToRgb(color as string))
        }
    )

    it('horizontal orientation uses flex-wrap', () => {
        const { container } = render(<Legend items={ITEMS} dataAttr="legend-h" />)
        const root = container.querySelector('[data-attr="legend-h"]')!
        expect(root.className).toContain('flex-row')
        expect(root.className).toContain('flex-wrap')
    })

    it('vertical orientation uses flex-col and does not wrap', () => {
        const { container } = render(<Legend items={ITEMS} orientation="vertical" dataAttr="legend-v" />)
        const root = container.querySelector('[data-attr="legend-v"]')!
        expect(root.className).toContain('flex-col')
        expect(root.className).not.toContain('flex-wrap')
    })

    it.each([
        ['start', 'justify-start'],
        ['center', 'justify-center'],
        ['end', 'justify-end'],
    ] as const)('align=%s applies %s', (align, expected) => {
        const { container } = render(<Legend items={ITEMS} align={align} dataAttr="legend" />)
        const root = container.querySelector('[data-attr="legend"]')!
        expect(root.className).toContain(expected)
    })

    it('renders items as non-button spans when onItemClick is omitted', () => {
        const { container } = render(<Legend items={ITEMS} />)
        expect(container.querySelectorAll('button')).toHaveLength(0)
        expect(container.querySelectorAll('[data-attr^="hog-charts-legend-item-"]').length).toBe(ITEMS.length)
    })

    it('renders items as buttons and fires onItemClick with the item key when set', () => {
        const onClick = jest.fn()
        const { container } = render(<Legend items={ITEMS} onItemClick={onClick} />)
        const buttons = container.querySelectorAll('button')
        expect(buttons).toHaveLength(ITEMS.length)

        fireEvent.click(buttons[1])
        expect(onClick).toHaveBeenCalledTimes(1)
        expect(onClick).toHaveBeenCalledWith('returning')

        fireEvent.click(buttons[3])
        expect(onClick).toHaveBeenLastCalledWith('dormant')
    })

    it('dims only the rows whose key is in hiddenKeys, leaving others at full opacity', () => {
        const { container } = render(<Legend items={ITEMS} hiddenKeys={['returning', 'dormant']} />)
        const dimmedByKey: Record<string, boolean> = {}
        const rows = container.querySelectorAll<HTMLElement>('[data-attr^="hog-charts-legend-item-"]')
        rows.forEach((row) => {
            const key = row.getAttribute('data-attr')!.replace('hog-charts-legend-item-', '')
            dimmedByKey[key] = row.className.includes('opacity-40')
        })
        expect(dimmedByKey).toEqual({ new: false, returning: true, resurrecting: false, dormant: true })
    })

    it('renders nothing when items is empty', () => {
        const { container } = render(<Legend items={[]} />)
        expect(container.firstChild).toBeNull()
    })

    it('does not import from kea, posthog-js, or lib/lemon-ui (MCP-bundle-safe)', () => {
        const source = fs.readFileSync(path.join(__dirname, 'Legend.tsx'), 'utf8')
        expect(source).not.toMatch(/from ['"]kea['"]/)
        expect(source).not.toMatch(/from ['"]posthog-js['"]/)
        expect(source).not.toMatch(/from ['"]~\/lib\/lemon-ui/)
        expect(source).not.toMatch(/from ['"]lib\/lemon-ui/)
        expect(source).not.toMatch(/from ['"]~\/scenes\//)
        expect(source).not.toMatch(/from ['"]scenes\//)
    })
})
