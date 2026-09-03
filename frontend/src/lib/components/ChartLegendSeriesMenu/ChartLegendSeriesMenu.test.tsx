import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ChartLegendSeriesMenu, type ChartLegendSeriesMenuProps } from './ChartLegendSeriesMenu'

const BASE: Omit<ChartLegendSeriesMenuProps, 'children'> = {
    seriesLabel: 'Pageviews',
    seriesColor: '#1d4aff',
    isHidden: false,
    isOnlyVisible: false,
    areAllVisible: true,
    canIsolate: true,
    onToggle: jest.fn(),
    onIsolate: jest.fn(),
    onToggleAll: jest.fn(),
}

function openMenu(props: Partial<ChartLegendSeriesMenuProps> = {}): void {
    const { container } = render(
        <ChartLegendSeriesMenu {...BASE} {...props}>
            <button type="button" data-attr="legend-row">
                Pageviews
            </button>
        </ChartLegendSeriesMenu>
    )
    fireEvent.contextMenu(container.querySelector('[data-attr="legend-row"]')!)
}

function menuRowText(): (string | null)[] {
    return screen.getAllByRole('menuitem').map((item) => item.textContent)
}

/** Text of every row carrying a gesture hint, so a hint that vanishes or lands on the wrong row shows up. */
function gestureRowText(): (string | null)[] {
    return Array.from(document.querySelectorAll('[data-attr="chart-legend-menu-gesture"]')).map(
        (hint) => hint.closest('[role="menuitem"]')!.textContent
    )
}

describe('ChartLegendSeriesMenu', () => {
    // The menu content renders in a portal, so an unmounted case would otherwise leave its rows
    // behind and the next one would match both.
    afterEach(cleanup)

    // Gesture hints are off by default here, so a row's text is exactly its label; the cases below
    // that turn them on assert the appended hint.
    it.each([
        {
            name: 'offers isolating and hiding when every series is visible',
            props: {},
            expected: ['Show only this series', 'Hide this series', 'Hide all series'],
        },
        {
            name: 'offers restoring everything from the isolated series, without repeating show-all',
            props: { isOnlyVisible: true, areAllVisible: false },
            expected: ['Show all series', 'Hide this series'],
        },
        {
            name: 'offers showing a hidden series back',
            props: { isHidden: true, areAllVisible: false },
            expected: ['Show only this series', 'Show this series', 'Show all series'],
        },
        {
            name: 'drops the bulk actions on a single-series legend',
            props: { canIsolate: false },
            expected: ['Hide this series'],
        },
    ])('$name', ({ props, expected }) => {
        openMenu(props)

        expect(menuRowText()).toEqual(expected)
    })

    it('teaches the click gestures, on the rows those gestures reach', () => {
        openMenu({ showGestureHints: true })

        // KeyboardShortcut renders the platform modifier, which is `ctrl` under jsdom.
        expect(gestureRowText()).toEqual(['Show only this seriesclick', 'Hide this seriesctrlclick'])
    })

    it('advertises no gesture on a legend whose rows only toggle', () => {
        openMenu()

        expect(gestureRowText()).toEqual([])
    })

    it('names the series the menu acts on, since rows sit close together', () => {
        openMenu({ seriesLabel: 'Signups' })

        expect(screen.getByTitle('Signups')).toBeInTheDocument()
    })

    it.each([
        { label: 'Show only this series', handler: 'onIsolate' as const },
        { label: 'Hide this series', handler: 'onToggle' as const },
        { label: 'Hide all series', handler: 'onToggleAll' as const },
    ])('runs $handler when "$label" is picked', ({ label, handler }) => {
        const handlers = { onToggle: jest.fn(), onIsolate: jest.fn(), onToggleAll: jest.fn() }
        openMenu(handlers)

        const item = screen.getAllByRole('menuitem').find((el) => el.textContent?.startsWith(label))!
        fireEvent.click(item)

        expect(handlers[handler]).toHaveBeenCalledTimes(1)
        expect(Object.values(handlers).filter((fn) => fn.mock.calls.length > 0)).toHaveLength(1)
    })
})
