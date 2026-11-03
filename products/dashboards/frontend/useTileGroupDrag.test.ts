import { act, renderHook } from '@testing-library/react'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { TAKE_OUT_DROP_ZONE_KEY, useTileGroupDrag } from './useTileGroupDrag'

const box = (id: number, y: number): LayoutItem => ({ i: String(id), x: 0, y, w: 6, h: 2 })

const band = (key: string, withGrid = true): HTMLElement => {
    const element = document.createElement('div')
    element.setAttribute('data-dashboard-section', key)
    if (withGrid) {
        const grid = document.createElement('div')
        grid.setAttribute('data-dashboard-section-grid', key)
        grid.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200 }) as DOMRect
        element.append(grid)
    }
    return element
}

const dashboardRoot = (...bands: HTMLElement[]): HTMLElement => {
    const root = document.createElement('div')
    root.className = 'dashboard-items-wrapper'
    root.append(...bands)
    document.body.append(root)
    return root
}

const pointerAt = (...elements: Element[]): void => {
    Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: () => elements })
}

interface Dashboard {
    root: HTMLElement
    sourceBand: HTMLElement
    placeholder: HTMLElement
    openBand: HTMLElement
    closedBand: HTMLElement
    dropZone: HTMLElement
}

interface DropCase {
    name: string
    passOver?: (dashboard: Dashboard) => Element
    dropOn: (dashboard: Dashboard) => Element[]
    sourceKey?: string
    moved: [number, string | null, { x: number; y: number } | null] | null
    restored: boolean
}

describe('useTileGroupDrag', () => {
    const layout: Layout = [box(1, 0), box(2, 2)]
    const draggedItem = box(1, 40)

    const setUp = (
        sourceKey = 'group-plans'
    ): {
        dashboard: Dashboard
        tileElement: HTMLElement
        moveTileToSection: jest.Mock
        restoreLayout: jest.Mock
        result: { current: ReturnType<typeof useTileGroupDrag> }
        rerender: (props: { enabled: boolean }) => void
    } => {
        const dashboard = {
            sourceBand: band(sourceKey),
            openBand: band('group-ops'),
            closedBand: band('group-closed', false),
            dropZone: band(TAKE_OUT_DROP_ZONE_KEY, false),
        }
        const root = dashboardRoot(dashboard.sourceBand, dashboard.openBand, dashboard.closedBand, dashboard.dropZone)
        const tileElement = document.createElement('div')
        // A column is 100 pixels and a row 80, so this tile sits at column 3, row 2 of the band under it.
        tileElement.getBoundingClientRect = () => ({ left: 300, top: 160 }) as DOMRect
        dashboard.sourceBand.append(tileElement)
        const placeholder = document.createElement('div')
        placeholder.className = 'react-grid-placeholder'
        dashboard.sourceBand.append(placeholder)
        const moveTileToSection = jest.fn()
        const restoreLayout = jest.fn()
        const { result, rerender } = renderHook(
            ({ enabled }: { enabled: boolean }) =>
                useTileGroupDrag({
                    enabled,
                    sections: [],
                    rowHeight: 80,
                    margin: [0, 0],
                    layout,
                    moveTileToSection,
                    restoreLayout,
                }),
            { initialProps: { enabled: true } }
        )
        act(() => result.current.startTileDrag(draggedItem, tileElement))
        return {
            dashboard: { root, placeholder, ...dashboard },
            tileElement,
            moveTileToSection,
            restoreLayout,
            result,
            rerender,
        }
    }

    const drop = async (
        result: { current: ReturnType<typeof useTileGroupDrag> },
        tileElement: HTMLElement
    ): Promise<void> => {
        act(() =>
            result.current.finishTileDrag(
                draggedItem,
                tileElement,
                new MouseEvent('mouseup', { clientX: 10, clientY: 10 })
            )
        )
        await Promise.resolve()
    }

    afterEach(() => {
        document.body.innerHTML = ''
    })

    it.each<DropCase>([
        {
            name: 'on another band at the cell under the tile',
            dropOn: (dashboard) => [dashboard.openBand],
            moved: [1, 'group-ops', { x: 3, y: 2 }],
            restored: false,
        },
        {
            name: 'on a closed group, which has no cell',
            dropOn: (dashboard) => [dashboard.closedBand],
            moved: [1, 'group-closed', null],
            restored: false,
        },
        {
            name: 'on a closed group under the placeholder that followed it',
            dropOn: (dashboard) => [dashboard.placeholder, dashboard.closedBand],
            moved: [1, 'group-closed', null],
            restored: false,
        },
        {
            name: 'on the drop zone without a group to leave',
            sourceKey: 'tiles-start',
            dropOn: (dashboard) => [dashboard.dropZone],
            moved: null,
            restored: true,
        },
        {
            name: 'on the drop zone, out of its group',
            dropOn: (dashboard) => [dashboard.dropZone],
            moved: [1, null, null],
            restored: false,
        },
        {
            name: 'inside its own band',
            dropOn: (dashboard) => [dashboard.sourceBand],
            moved: null,
            restored: false,
        },
        {
            name: 'in a gap after passing over another band',
            passOver: (dashboard) => dashboard.openBand,
            dropOn: (dashboard) => [dashboard.root],
            moved: [1, 'group-ops', { x: 3, y: 2 }],
            restored: false,
        },
        {
            name: 'outside its dashboard',
            dropOn: () => [document.body],
            moved: null,
            restored: true,
        },
        {
            name: 'on a band of another dashboard',
            dropOn: () => [dashboardRoot(band('group-ops')).firstElementChild!],
            moved: null,
            restored: true,
        },
    ])('a tile dropped $name', async ({ passOver, dropOn, sourceKey, moved, restored }) => {
        const { dashboard, tileElement, moveTileToSection, restoreLayout, result } = setUp(sourceKey)

        if (passOver) {
            pointerAt(passOver(dashboard))
            act(() => result.current.trackTileDrag(new MouseEvent('mousemove', { clientX: 10, clientY: 10 })))
            expect(result.current.dropTargetKey).toBe('group-ops')
        }
        pointerAt(...dropOn(dashboard))
        await drop(result, tileElement)

        expect(moveTileToSection.mock.calls).toEqual(moved ? [moved] : [])
        expect(restoreLayout.mock.calls).toEqual(restored ? [[layout]] : [])
    })

    it('ignores a drop once edit mode turns off mid-drag', async () => {
        const { dashboard, tileElement, moveTileToSection, restoreLayout, result, rerender } = setUp()

        rerender({ enabled: false })
        expect(result.current.frozenSourceGrid).toBeNull()
        pointerAt(dashboard.openBand)
        await drop(result, tileElement)

        expect(moveTileToSection).not.toHaveBeenCalled()
        expect(restoreLayout).not.toHaveBeenCalled()
    })
})
