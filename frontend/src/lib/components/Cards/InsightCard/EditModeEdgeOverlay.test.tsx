import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import {
    EditModeEdgeOverlay,
    isPointInScrollbarGutter,
    useResizeHandleScrollbarPassThrough,
} from './EditModeEdgeOverlay'

type FakeElementConfig = {
    rect: { left: number; top: number; right: number; bottom: number }
    offsetWidth: number
    offsetHeight: number
    clientWidth: number
    clientHeight: number
    scrollWidth: number
    scrollHeight: number
    border?: number
    direction?: 'ltr' | 'rtl'
    overflowX?: string
    overflowY?: string
}

// A 400x300 element with classic 15px scrollbars: clientWidth/Height shrink by the scrollbar
// (and borders, when set), and content overflows on both axes unless a case says otherwise.
const SCROLLABLE_BASE: FakeElementConfig = {
    rect: { left: 0, top: 0, right: 400, bottom: 300 },
    offsetWidth: 400,
    offsetHeight: 300,
    clientWidth: 385,
    clientHeight: 285,
    scrollWidth: 800,
    scrollHeight: 600,
}

describe('EditModeEdgeOverlay', () => {
    const styleConfig = new WeakMap<
        Element,
        { border: number; direction: string; overflowX: string; overflowY: string }
    >()
    const realGetComputedStyle = window.getComputedStyle

    beforeEach(() => {
        cleanup()
        jest.spyOn(window, 'getComputedStyle').mockImplementation((el: Element): CSSStyleDeclaration => {
            const config = styleConfig.get(el)
            if (!config) {
                return realGetComputedStyle(el)
            }
            return {
                borderTopWidth: `${config.border}px`,
                borderBottomWidth: `${config.border}px`,
                borderLeftWidth: `${config.border}px`,
                borderRightWidth: `${config.border}px`,
                direction: config.direction,
                overflowX: config.overflowX,
                overflowY: config.overflowY,
            } as CSSStyleDeclaration
        })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    function fakeScrollableElement({
        rect,
        border = 0,
        direction = 'ltr',
        overflowX = 'auto',
        overflowY = 'auto',
        ...dimensions
    }: FakeElementConfig): HTMLElement {
        const el = document.createElement('div')
        Object.defineProperties(
            el,
            Object.fromEntries(Object.entries(dimensions).map(([key, value]) => [key, { value }]))
        )
        el.getBoundingClientRect = () =>
            ({ ...rect, width: rect.right - rect.left, height: rect.bottom - rect.top }) as DOMRect
        styleConfig.set(el, { border, direction, overflowX, overflowY })
        return el
    }

    it('renders eight edge and corner hit areas with data attr', () => {
        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)

        const zones = getAllByTitle('Click to edit layout')
        expect(zones).toHaveLength(8)
        zones.forEach((zone) => {
            expect(zone).toHaveAttribute('data-attr', 'dashboard-edit-mode-from-card-edge')
        })
    })

    it.each([
        [0, 'n'],
        [1, 's'],
        [2, 'w'],
        [3, 'e'],
        [4, 'nw'],
        [5, 'ne'],
        [6, 'sw'],
        [7, 'se'],
    ])('calls onEnterEditMode with the pressed direction when zone %i is pressed', (zoneIndex, expectedEdge) => {
        const onEnterEditMode = jest.fn()

        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={onEnterEditMode} />)
        const zones = getAllByTitle('Click to edit layout')

        fireEvent.mouseDown(zones[zoneIndex])
        expect(onEnterEditMode).toHaveBeenCalledTimes(1)
        expect(onEnterEditMode).toHaveBeenCalledWith(expect.anything(), expectedEdge)
    })

    it('reveals all resize handles while any zone is hovered', () => {
        const { container, getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)
        const zones = getAllByTitle('Click to edit layout')

        expect(container.querySelectorAll('.handle')).toHaveLength(0)

        fireEvent.mouseEnter(zones[0])
        expect(container.querySelectorAll('.handle')).toHaveLength(8)

        fireEvent.mouseLeave(zones[0])
        expect(container.querySelectorAll('.handle')).toHaveLength(0)
    })

    it('keeps handles shown while moving between overlapping zones', () => {
        const { container, getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)
        const zones = getAllByTitle('Click to edit layout')

        // Enter a corner, then the adjacent edge, before leaving the corner — count must not hit zero.
        fireEvent.mouseEnter(zones[0])
        fireEvent.mouseEnter(zones[4])
        fireEvent.mouseLeave(zones[0])
        expect(container.querySelectorAll('.handle')).toHaveLength(8)
    })

    describe('scrollbar pass-through', () => {
        // A table tile's horizontal scrollbar renders in the card's bottom pixels, right under the
        // "s" zone. Presses aimed at it must scroll, not throw the user into edit mode.
        function renderWithScrollableUnderneath(): {
            onEnterEditMode: jest.Mock
            zones: HTMLElement[]
            scrollable: HTMLElement
        } {
            const onEnterEditMode = jest.fn()
            const { container, getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={onEnterEditMode} />)
            const zones = getAllByTitle('Click to edit layout')
            const scrollable = fakeScrollableElement(SCROLLABLE_BASE)
            container.appendChild(scrollable)
            jest.spyOn(document, 'elementsFromPoint').mockImplementation((x: number, y: number) =>
                x >= 0 && x <= 400 && y >= 0 && y <= 300 ? [zones[1], scrollable] : []
            )
            return { onEnterEditMode, zones, scrollable }
        }

        it('does not enter edit mode when the press lands on a scrollbar under the zone', () => {
            const { onEnterEditMode, zones } = renderWithScrollableUnderneath()

            fireEvent.mouseDown(zones[1], { clientX: 200, clientY: 292 })
            expect(onEnterEditMode).not.toHaveBeenCalled()

            fireEvent.mouseDown(zones[1], { clientX: 200, clientY: 150 })
            expect(onEnterEditMode).toHaveBeenCalledTimes(1)
        })

        it('lets pointer events through while hovering a scrollbar and recaptures them after', () => {
            const { zones } = renderWithScrollableUnderneath()

            fireEvent.mouseMove(zones[1], { clientX: 200, clientY: 292 })
            expect(zones[1]).toHaveStyle({ pointerEvents: 'none' })

            fireEvent.mouseMove(document, { clientX: 200, clientY: 150 })
            expect(zones[1]).not.toHaveStyle({ pointerEvents: 'none' })
        })

        it('yields every zone stacked on the point, not just the hovered one', () => {
            const { zones } = renderWithScrollableUnderneath()
            // Corner zones paint above edge zones near card corners. jsdom has no layout, so give the
            // sw corner and s edge zones their real overlapping geometry at the card's bottom-left.
            const rects: Array<[number, { left: number; top: number; right: number; bottom: number }]> = [
                [1, { left: 0, top: 288, right: 400, bottom: 302 }],
                [6, { left: -2, top: 284, right: 16, bottom: 302 }],
            ]
            for (const [index, rect] of rects) {
                zones[index].getBoundingClientRect = () =>
                    ({ ...rect, width: rect.right - rect.left, height: rect.bottom - rect.top }) as DOMRect
            }

            fireEvent.mouseMove(zones[6], { clientX: 8, clientY: 292 })

            expect(zones[6]).toHaveStyle({ pointerEvents: 'none' })
            expect(zones[1]).toHaveStyle({ pointerEvents: 'none' })
        })
    })

    describe('useResizeHandleScrollbarPassThrough', () => {
        // In edit mode react-grid-layout's south resize handle covers a table tile's horizontal
        // scrollbar, so presses there resized the tile instead of scrolling.
        function Harness(): null {
            useResizeHandleScrollbarPassThrough(true)
            return null
        }

        function mountEditModeTile(): { gridItem: HTMLElement; handle: HTMLElement; scrollable: HTMLElement } {
            const gridItem = document.createElement('div')
            gridItem.className = 'react-grid-item'
            const scrollable = fakeScrollableElement(SCROLLABLE_BASE)
            const handle = document.createElement('span')
            handle.className = 'react-resizable-handle react-resizable-handle-s'
            handle.getBoundingClientRect = () =>
                ({ left: 0, top: 276, right: 368, bottom: 308, width: 368, height: 32 }) as DOMRect
            gridItem.append(scrollable, handle)
            document.body.appendChild(gridItem)
            jest.spyOn(document, 'elementsFromPoint').mockImplementation((x: number, y: number) =>
                x >= 0 && x <= 400 && y >= 0 && y <= 300 ? [handle, scrollable, gridItem] : []
            )
            render(<Harness />)
            return { gridItem, handle, scrollable }
        }

        afterEach(() => {
            document.querySelectorAll('.react-grid-item').forEach((el) => el.remove())
        })

        it('yields a resize handle while over a scrollbar and re-arms it after', () => {
            const { handle } = mountEditModeTile()

            fireEvent.mouseMove(handle, { clientX: 200, clientY: 292 })
            expect(handle.style.pointerEvents).toBe('none')

            fireEvent.mouseMove(document, { clientX: 200, clientY: 150 })
            expect(handle.style.pointerEvents).toBe('')
        })

        it('yields every handle stacked on the point, not just the hovered one', () => {
            const { gridItem, handle } = mountEditModeTile()
            const cornerHandle = document.createElement('span')
            cornerHandle.className = 'react-resizable-handle react-resizable-handle-sw'
            cornerHandle.getBoundingClientRect = () =>
                ({ left: -8, top: 276, right: 24, bottom: 308, width: 32, height: 32 }) as DOMRect
            gridItem.appendChild(cornerHandle)

            fireEvent.mouseMove(cornerHandle, { clientX: 8, clientY: 292 })

            expect(cornerHandle.style.pointerEvents).toBe('none')
            expect(handle.style.pointerEvents).toBe('none')
        })

        it('stops a press over a scrollbar from reaching the grid item, but not one elsewhere', () => {
            const { gridItem, scrollable } = mountEditModeTile()
            const gridItemPress = jest.fn()
            gridItem.addEventListener('mousedown', gridItemPress)

            fireEvent.mouseDown(scrollable, { clientX: 200, clientY: 292 })
            expect(gridItemPress).not.toHaveBeenCalled()

            fireEvent.mouseDown(scrollable, { clientX: 200, clientY: 150 })
            expect(gridItemPress).toHaveBeenCalledTimes(1)
        })
    })

    describe('isPointInScrollbarGutter', () => {
        test.each<[string, Partial<FakeElementConfig>, [number, number], boolean]>([
            ['point on the horizontal scrollbar', {}, [200, 292], true],
            ['point on the vertical scrollbar (ltr: right edge)', {}, [392, 150], true],
            ['point in the content area', {}, [200, 150], false],
            ['point outside the element', {}, [200, 310], false],
            [
                'horizontal gutter reserved but content does not overflow',
                { scrollWidth: 385, scrollHeight: 285 },
                [200, 292],
                false,
            ],
            // Overlay scrollbars (macOS default): no layout gutter, so the edge band of a genuinely
            // scrollable element counts as scrollbar territory.
            ['overlay: point in the bottom scroll band', { clientWidth: 400, clientHeight: 300 }, [200, 292], true],
            ['overlay: point above the bottom scroll band', { clientWidth: 400, clientHeight: 300 }, [200, 283], false],
            ['overlay: point in the right scroll band', { clientWidth: 400, clientHeight: 300 }, [392, 150], true],
            [
                'overlay rtl: scroll band sits on the left edge',
                { clientWidth: 400, clientHeight: 300, direction: 'rtl' as const },
                [7, 150],
                true,
            ],
            [
                'overflow hidden clips without a scrollbar',
                { clientWidth: 400, clientHeight: 300, overflowX: 'hidden', overflowY: 'hidden' },
                [200, 292],
                false,
            ],
            [
                'point on the bottom border, just below the gutter',
                { border: 2, clientWidth: 381, clientHeight: 281 },
                [200, 299],
                false,
            ],
            [
                'point on the horizontal scrollbar of a bordered element',
                { border: 2, clientWidth: 381, clientHeight: 281 },
                [200, 290],
                true,
            ],
            ['rtl: vertical scrollbar sits on the left edge', { direction: 'rtl' }, [7, 150], true],
            ['rtl: right edge is plain content', { direction: 'rtl' }, [392, 150], false],
        ])('%s', (_name, overrides, [x, y], expected) => {
            expect(isPointInScrollbarGutter(fakeScrollableElement({ ...SCROLLABLE_BASE, ...overrides }), x, y)).toBe(
                expected
            )
        })
    })
})
