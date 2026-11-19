import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'

import { expect } from 'storybook/test'

import { DashboardV2Scene } from './DashboardV2Scene'
import { GRID } from './layout/dashboardTypes'

const meta: Meta<typeof DashboardV2Scene> = {
    title: 'Scenes-App/Dashboards v2',
    component: DashboardV2Scene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.DASHBOARDS_V2],
        // The scene is one product's page with invented data; a render error or a failed play still fails CI.
        // The plays drag between tiles that must be on screen together, so the page is taller than the default.
        testOptions: { snapshotBrowsers: [], viewport: { width: 1280, height: 1100 } },
    },
}
export default meta

type Story = StoryObj<typeof DashboardV2Scene>

interface Box {
    left: number
    top: number
    width: number
    height: number
}

function tileElement(canvas: HTMLElement, id: string): HTMLElement {
    const element = canvas.querySelector<HTMLElement>(`[data-dv2-tile="${id}"]`)
    if (!element) {
        throw new Error(`No tile "${id}" on the page`)
    }
    return element
}

function boxOf(element: Element): Box {
    const { left, top, width, height } = element.getBoundingClientRect()
    return { left: Math.round(left), top: Math.round(top), width: Math.round(width), height: Math.round(height) }
}

/** The grid a tile is in, by the id the grid carries. */
function gridOf(canvas: HTMLElement, id: string): string | undefined {
    return tileElement(canvas, id).parentElement?.closest<HTMLElement>('[data-dv2-grid]')?.dataset.dv2Grid
}

function overlappingPairs(canvas: HTMLElement): string[] {
    const pairs: string[] = []
    for (const grid of canvas.querySelectorAll('[data-dv2-grid]')) {
        const tiles = [...grid.querySelectorAll<HTMLElement>(':scope > .react-grid-layout > [data-dv2-tile]')]
        const boxes = tiles.map((tile) => ({ id: tile.dataset.dv2Tile, ...boxOf(tile) }))
        for (const a of boxes) {
            for (const b of boxes) {
                const apart =
                    a.left + a.width <= b.left + 1 ||
                    b.left + b.width <= a.left + 1 ||
                    a.top + a.height <= b.top + 1 ||
                    b.top + b.height <= a.top + 1
                if (a.id! < b.id! && !apart) {
                    pairs.push(`${a.id} and ${b.id}`)
                }
            }
        }
    }
    return pairs
}

const nextFrame = (): Promise<void> => new Promise((resolve) => requestAnimationFrame(() => resolve()))

const STEP_PX = 16

function landingSpot(canvas: HTMLElement): HTMLElement {
    const spots = [
        ...canvas.querySelectorAll<HTMLElement>('.react-grid-placeholder, .DashboardV2__drop-preview'),
    ].filter((spot) => getComputedStyle(spot).display !== 'none')
    expect(spots).toHaveLength(1)
    return spots[0]
}

/**
 * Carries a tile by its handle until its top-left corner is at `corner`, in small steps as a hand would, and
 * stops with the button still down. Returns where the page says the tile will land, a function that moves the
 * pointer a little sideways, and a function that lets go.
 */
async function carryTile(
    canvas: HTMLElement,
    id: string,
    corner: { x: number; y: number }
): Promise<{ landing: Box; nudge: (dx: number) => Promise<void>; release: () => Promise<void> }> {
    const tile = tileElement(canvas, id)
    const handle = tile.querySelector<HTMLElement>('.DashboardV2__handle') ?? tile
    const grip = handle.getBoundingClientRect()
    const start = tile.getBoundingClientRect()
    const from = { x: grip.left + 40, y: grip.top + 12 }
    const to = { x: corner.x + (from.x - start.left), y: corner.y + (from.y - start.top) }
    for (const point of [from, to]) {
        // The page finds the grid under the pointer by hit-testing, which finds nothing outside the window.
        if (point.x < 0 || point.y < 0 || point.x > window.innerWidth || point.y > window.innerHeight) {
            throw new Error(`The drag of "${id}" goes off screen at ${Math.round(point.x)},${Math.round(point.y)}`)
        }
    }
    fireEvent.mouseDown(handle, { clientX: from.x, clientY: from.y, button: 0 })
    // The grid library starts a drag on the first move, so that move must not carry any distance.
    fireEvent.mouseMove(document, { clientX: from.x, clientY: from.y })
    // The grid records the start of the drag on its next render. A move before that is lost, and the tile would
    // trail the pointer by that much for the rest of the drag.
    await nextFrame()
    await nextFrame()
    const steps = Math.ceil(Math.hypot(to.x - from.x, to.y - from.y) / STEP_PX)
    for (let step = steps - 1; step >= 0; step--) {
        // Counted back from the end, so the last step is a whole one and can cross into a new cell.
        fireEvent.mouseMove(document, {
            clientX: to.x - ((to.x - from.x) * step * STEP_PX) / (steps * STEP_PX),
            clientY: to.y - ((to.y - from.y) * step * STEP_PX) / (steps * STEP_PX),
        })
        await nextFrame()
    }
    // The tile itself is under the pointer while it is carried, not only its landing spot.
    await waitFor(() => {
        const carried = boxOf(tile)
        expect(Math.abs(carried.left - corner.x)).toBeLessThan(3)
        expect(Math.abs(carried.top - corner.y)).toBeLessThan(3)
    })
    // The landing spot slides into place. Its inline style is where it is going, so wait for that to stop
    // changing, then for the slide itself to end.
    let target = ''
    await waitFor(() => {
        const now = landingSpot(canvas).style.cssText
        const settled = now === target
        target = now
        expect(settled).toBe(true)
    })
    await Promise.all(
        landingSpot(canvas)
            .getAnimations()
            .map((animation) => animation.finished)
    )
    const landing = boxOf(landingSpot(canvas))
    return {
        landing,
        nudge: async (dx: number) => {
            fireEvent.mouseMove(document, { clientX: to.x + dx, clientY: to.y })
            await nextFrame()
        },
        release: async () => {
            fireEvent.mouseUp(document, { clientX: to.x, clientY: to.y })
            await waitFor(() => expect(canvas.querySelector('.react-draggable-dragging')).toBeNull())
        },
    }
}

/** A tile must end exactly where the page showed it would, and no two tiles may share space afterwards. */
async function expectLandsOnPreview(canvas: HTMLElement, id: string, landing: Box): Promise<void> {
    await waitFor(() => expect(boxOf(tileElement(canvas, id))).toEqual(landing))
    // The tiles around it slide into their new places, so this waits for them to stop.
    await waitFor(() => expect(overlappingPairs(canvas)).toEqual([]))
}

export const Editor: Story = {}

export const MoveTileWithinGrid: Story = {
    play: async ({ canvasElement }) => {
        await waitFor(() => tileElement(canvasElement, 'ks-headless'))
        const tile = tileElement(canvasElement, 'ks-headless')
        tile.scrollIntoView({ block: 'center' })
        const start = boxOf(tile)
        const grid = boxOf(canvasElement.querySelector('[data-dv2-grid="kitchen-sink"]')!)
        const columnPitch = (grid.width + GRID.gapPx) / GRID.columns
        // Just past the middle of column 12, so the last step of the carry is the one that crosses into column 13.
        // The landing spot must follow that last step, not the one before it.
        const { landing, release } = await carryTile(canvasElement, 'ks-headless', {
            x: grid.left + 12.6 * columnPitch,
            y: start.top + 6,
        })
        expect(Math.abs(landing.left - (grid.left + 13 * columnPitch))).toBeLessThan(2)
        expect(landing.top).toBe(start.top)

        await release()
        await expectLandsOnPreview(canvasElement, 'ks-headless', landing)
        expect(gridOf(canvasElement, 'ks-headless')).toBe('kitchen-sink')
    },
}

export const RowMakesRoomForDroppedTile: Story = {
    play: async ({ canvasElement }) => {
        await waitFor(() => tileElement(canvasElement, 'ks-notes'))
        const row = ['ks-stat-0', 'ks-stat-1', 'ks-stat-2', 'ks-stat-3']
        const rowTop = boxOf(tileElement(canvasElement, 'ks-stat-0')).top
        const second = boxOf(tileElement(canvasElement, 'ks-stat-1'))
        const { landing, release } = await carryTile(canvasElement, 'ks-notes', {
            x: second.left + 20,
            y: second.top + 8,
        })
        await release()
        await expectLandsOnPreview(canvasElement, 'ks-notes', landing)

        // The full row took the fifth tile by getting narrower, so nothing was pushed to another row.
        for (const id of [...row, 'ks-notes']) {
            expect(boxOf(tileElement(canvasElement, id)).top).toBe(rowTop)
        }
    },
}

export const DropTileIntoSection: Story = {
    play: async ({ canvasElement }) => {
        await waitFor(() => tileElement(canvasElement, 'ks-s-bar'))
        const inside = boxOf(tileElement(canvasElement, 'ks-s-bar'))
        const { landing, release } = await carryTile(canvasElement, 'ks-stat-0', {
            x: inside.left + 360,
            y: inside.top + 88,
        })
        // The outline is in the section, on the row the tile was dropped on.
        expect(landing.top).toBe(inside.top)

        await release()
        await waitFor(() => expect(gridOf(canvasElement, 'ks-stat-0')).toBe('ks-section'))
        await expectLandsOnPreview(canvasElement, 'ks-stat-0', landing)
    },
}

export const DragTileOutOfNestedSection: Story = {
    play: async ({ canvasElement }) => {
        await waitFor(() => tileElement(canvasElement, 'ks-i-line'))
        const chart = boxOf(tileElement(canvasElement, 'ks-trend'))
        const { landing, release } = await carryTile(canvasElement, 'ks-i-line', {
            x: chart.left + 160,
            y: chart.top + 28,
        })
        // The outline is in the tab's grid, on the row of the chart the tile was dropped on.
        expect(landing.top).toBe(chart.top)

        await release()
        await waitFor(() => expect(gridOf(canvasElement, 'ks-i-line')).toBe('kitchen-sink'))
        await expectLandsOnPreview(canvasElement, 'ks-i-line', landing)
    },
}

export const DragTileJustBelowItsSection: Story = {
    play: async ({ canvasElement }) => {
        await waitFor(() => tileElement(canvasElement, 'ks-l-bar'))
        const tile = tileElement(canvasElement, 'ks-l-bar')
        tile.scrollIntoView({ block: 'center' })
        const start = boxOf(tile)
        // The tile is the only one in its section, so the section is as tall as the tile. This puts the pointer
        // just under the section.
        const { nudge, release } = await carryTile(canvasElement, 'ks-l-bar', {
            x: start.left + 4,
            y: start.top + start.height + 8,
        })
        // Leaving closes the section up. The tile must stay out of it while the pointer stays where it is: each
        // small move used to send the outline back into the section and out again.
        const grids: (string | undefined)[] = []
        for (const dx of [1, 0, 1, 0, 1, 0]) {
            await nudge(dx)
            grids.push(landingSpot(canvasElement).closest<HTMLElement>('[data-dv2-grid]')?.dataset.dv2Grid)
        }
        expect(grids).toEqual(Array(6).fill('kitchen-sink'))
        const landing = boxOf(landingSpot(canvasElement))

        await release()
        await waitFor(() => expect(gridOf(canvasElement, 'ks-l-bar')).toBe('kitchen-sink'))
        await expectLandsOnPreview(canvasElement, 'ks-l-bar', landing)
    },
}
