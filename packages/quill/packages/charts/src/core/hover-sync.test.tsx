import { render } from '@testing-library/react'

import { buildSyncedIndexFinder, ChartHoverSync, useHoverSync } from './hover-sync'

function Probe({ id, labels, hovered }: { id: string; labels: string[]; hovered: string | null }): JSX.Element {
    return <span data-attr={id}>{useHoverSync(labels, hovered)}</span>
}

const DAYS = ['2026-01-01', '2026-01-02', '2026-01-03']

describe('hover-sync', () => {
    it.each([
        ['matches an identical label', DAYS, '2026-01-02', 1],
        ['picks the nearest date', ['2026-01-01T00:00:00Z', '2026-01-01T00:10:00Z'], '2026-01-01T00:07:00Z', 1],
        ['ignores a date outside the range', DAYS, '2026-02-01', -1],
        ['ignores an unknown category', ['Mon', 'Tue'], 'Wed', -1],
        ['ignores a numeric category that is not a date', ['1', '3'], '2', -1],
    ])('buildSyncedIndexFinder %s', (_, labels, label, expected) => {
        expect(buildSyncedIndexFinder(labels)(label)).toBe(expected)
    })

    it('shares the hovered label with the other charts in the provider, not with the hovered one', () => {
        const ui = (a: string | null, b: string | null): JSX.Element => (
            <ChartHoverSync>
                <Probe id="a" labels={DAYS} hovered={a} />
                <Probe id="b" labels={DAYS} hovered={b} />
            </ChartHoverSync>
        )
        const { container, rerender } = render(ui('2026-01-03', null))
        const index = (id: string): string | null | undefined =>
            container.querySelector(`[data-attr="${id}"]`)?.textContent
        expect([index('a'), index('b')]).toEqual(['-1', '2'])

        // b takes over the hover before a clears its own, so a's clear must not wipe b's.
        rerender(ui('2026-01-03', '2026-01-01'))
        rerender(ui(null, '2026-01-01'))
        expect([index('a'), index('b')]).toEqual(['0', '-1'])

        rerender(ui(null, null))
        expect([index('a'), index('b')]).toEqual(['-1', '-1'])
    })

    it('leaves a chart with sync turned off out of the provider', () => {
        function Off({ hovered }: { hovered: string | null }): JSX.Element {
            return <span data-attr="off">{useHoverSync(DAYS, hovered, false)}</span>
        }
        const { container } = render(
            <ChartHoverSync>
                <Probe id="a" labels={DAYS} hovered="2026-01-02" />
                <Off hovered={null} />
            </ChartHoverSync>
        )
        expect(container.querySelector('[data-attr="off"]')?.textContent).toBe('-1')
    })

    it('does nothing outside a provider', () => {
        const { container } = render(<Probe id="a" labels={DAYS} hovered="2026-01-01" />)
        expect(container.textContent).toBe('-1')
    })
})
