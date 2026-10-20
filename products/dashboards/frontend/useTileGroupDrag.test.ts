import { act, renderHook } from '@testing-library/react'
import type { Layout, LayoutItem } from 'react-grid-layout'

import type { DashboardTile } from '~/types'

import { getDashboardGridCompactor } from './dashboardCustomization'
import type { DashboardSection } from './dashboardTileSections'
import type { DashboardTileGroupApi } from './generated/api.schemas'
import { useTileGroupDrag } from './useTileGroupDrag'

const tile = (id: number, group_key: string | null = null): DashboardTile =>
    ({ id, group_key, layouts: {}, color: null }) as DashboardTile

const box = (id: number, y: number): LayoutItem => ({ i: String(id), x: 0, y, w: 6, h: 2 })

const band = (key: string): HTMLElement => {
    const element = document.createElement('div')
    element.setAttribute('data-dashboard-section', key)
    // Mirrors DashboardItems.tsx: each band wraps a nested grid element finishTileDrag looks up by this attribute.
    const grid = document.createElement('div')
    grid.setAttribute('data-dashboard-section-grid', key)
    element.append(grid)
    return element
}

const dashboardRoot = (...bands: HTMLElement[]): HTMLElement => {
    const root = document.createElement('div')
    root.className = 'dashboard-items-wrapper'
    root.append(...bands)
    document.body.append(root)
    return root
}

interface OwnDashboard {
    root: HTMLElement
    sourceBand: HTMLElement
    opsBand: HTMLElement
}

describe('useTileGroupDrag', () => {
    const sections: DashboardSection[] = [
        { kind: 'tiles', key: 'tiles-start', tiles: [tile(1)] },
        {
            kind: 'group',
            key: 'group-ops',
            groupKey: 'ops',
            group: {} as DashboardTileGroupApi,
            tiles: [tile(2, 'ops')],
        },
    ]
    const layout: Layout = [box(1, 0), box(2, 2)]

    afterEach(() => {
        document.body.innerHTML = ''
    })

    it.each([
        {
            name: 'over another band of its own dashboard',
            dropOn: (own: OwnDashboard): Element => own.opsBand,
            moved: true,
            restored: false,
        },
        {
            name: 'inside its own band',
            dropOn: (own: OwnDashboard): Element => own.sourceBand,
            moved: false,
            restored: false,
        },
        {
            name: 'between the bands',
            dropOn: (own: OwnDashboard): Element => own.root,
            moved: false,
            restored: true,
        },
        {
            name: 'over a band of another dashboard',
            dropOn: (): Element => dashboardRoot(band('group-ops')).firstElementChild!,
            moved: false,
            restored: true,
        },
    ])('a tile dropped $name', async ({ dropOn, moved, restored }) => {
        const sourceBand = band('tiles-start')
        const opsBand = band('group-ops')
        const root = dashboardRoot(sourceBand, opsBand)
        const tileElement = document.createElement('div')
        sourceBand.append(tileElement)
        const target = dropOn({ root, sourceBand, opsBand })
        Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: () => [target] })
        const moveTileToGroup = jest.fn()
        const updateLayout = jest.fn()
        const { result } = renderHook(() =>
            useTileGroupDrag({
                sections,
                sectionLayouts: [[box(1, 0)], [box(2, 0)]],
                layout,
                collapsedTileGroupKeys: [],
                compactor: getDashboardGridCompactor(),
                rowHeight: 80,
                margin: [16, 16],
                enabled: true,
                toggleTileGroup: jest.fn(),
                moveTileToGroup,
                updateLayout,
            })
        )

        const draggedItem = box(1, 40)
        act(() => result.current.startTileDrag(draggedItem, tileElement))
        act(() =>
            result.current.finishTileDrag(
                draggedItem,
                tileElement,
                new MouseEvent('mouseup', { clientX: 10, clientY: 10 })
            )
        )
        await Promise.resolve()

        expect(moveTileToGroup).toHaveBeenCalledTimes(moved ? 1 : 0)
        expect(updateLayout.mock.calls).toEqual(restored ? [[layout]] : [])
    })

    it('places a cross-group drop at the pointer cell instead of always at the bottom', async () => {
        const sourceBand = band('tiles-start')
        const opsBand = band('group-ops')
        dashboardRoot(sourceBand, opsBand)
        const tileElement = document.createElement('div')
        sourceBand.append(tileElement)
        const grid = opsBand.querySelector('[data-dashboard-section-grid]') as HTMLElement
        grid.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200 }) as DOMRect
        tileElement.getBoundingClientRect = () => ({ left: 300, top: 160 }) as DOMRect
        Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: () => [opsBand] })
        const moveTileToGroup = jest.fn()
        const { result } = renderHook(() =>
            useTileGroupDrag({
                sections,
                sectionLayouts: [[box(1, 0)], [box(2, 0)]],
                layout,
                collapsedTileGroupKeys: [],
                compactor: getDashboardGridCompactor(),
                rowHeight: 80,
                margin: [0, 0],
                enabled: true,
                toggleTileGroup: jest.fn(),
                moveTileToGroup,
                updateLayout: jest.fn(),
            })
        )

        const draggedItem = box(1, 40)
        act(() => result.current.startTileDrag(draggedItem, tileElement))
        act(() =>
            result.current.finishTileDrag(
                draggedItem,
                tileElement,
                new MouseEvent('mouseup', { clientX: 10, clientY: 10 })
            )
        )
        await Promise.resolve()

        // gridRect.width 1200 / 12 cols = 100px/col; tileRect.left 300 -> column 3. rowHeight 80, tileRect.top 160 -> row 2.
        const movedTile = moveTileToGroup.mock.calls[0][2].find((item: LayoutItem) => item.i === '1')
        expect(movedTile).toMatchObject({ x: 3, y: 2 })
    })

    it('ignores a drop once edit mode turns off mid-drag', async () => {
        const sourceBand = band('tiles-start')
        const opsBand = band('group-ops')
        dashboardRoot(sourceBand, opsBand)
        const tileElement = document.createElement('div')
        sourceBand.append(tileElement)
        Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: () => [opsBand] })
        const moveTileToGroup = jest.fn()
        const updateLayout = jest.fn()
        const { result, rerender } = renderHook(
            (props: { enabled: boolean }) =>
                useTileGroupDrag({
                    sections,
                    sectionLayouts: [[box(1, 0)], [box(2, 0)]],
                    layout,
                    collapsedTileGroupKeys: [],
                    compactor: getDashboardGridCompactor(),
                    rowHeight: 80,
                    margin: [16, 16],
                    enabled: props.enabled,
                    toggleTileGroup: jest.fn(),
                    moveTileToGroup,
                    updateLayout,
                }),
            { initialProps: { enabled: true } }
        )

        const draggedItem = box(1, 40)
        act(() => result.current.startTileDrag(draggedItem, tileElement))

        // Escape exits edit mode without cancelling the drag already tracked by the browser.
        rerender({ enabled: false })
        expect(result.current.draggingTileId).toBeNull()
        expect(result.current.frozenSourceGrid).toBeNull()

        act(() =>
            result.current.finishTileDrag(
                draggedItem,
                tileElement,
                new MouseEvent('mouseup', { clientX: 10, clientY: 10 })
            )
        )
        await Promise.resolve()

        expect(moveTileToGroup).not.toHaveBeenCalled()
        expect(updateLayout).not.toHaveBeenCalled()
    })
})
