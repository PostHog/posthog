import type { MouseEvent as ReactMouseEvent } from 'react'

import { EditModeEdge } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import {
    EDIT_MODE_GESTURE_THRESHOLD_PX,
    continueDragGestureInEditMode,
    continueResizeGestureInEditMode,
    resolveResizeHandleDirection,
    whenPressBecomesDrag,
} from 'scenes/dashboard/editLayoutGesture'

describe('editLayoutGesture', () => {
    const rect = { left: 0, right: 300, top: 0, bottom: 200 }

    describe('resolveResizeHandleDirection', () => {
        it.each([
            ['n', 150, 0, 'n'],
            ['s', 150, 200, 's'],
            ['w', 0, 100, 'w'],
            ['e', 300, 100, 'e'],
            ['n', 10, 0, 'nw'],
            ['n', 295, 0, 'ne'],
            ['s', 10, 200, 'sw'],
            ['s', 295, 200, 'se'],
            ['w', 0, 10, 'nw'],
            ['w', 0, 195, 'sw'],
            ['e', 300, 10, 'ne'],
            ['e', 300, 195, 'se'],
            // Corner presses pass through directly, ignoring the edge-upgrade thresholds.
            ['nw', 150, 100, 'nw'],
            ['ne', 150, 100, 'ne'],
            ['sw', 150, 100, 'sw'],
            ['se', 150, 100, 'se'],
        ])('maps edge %s at (%i, %i) to handle %s', (edge, clientX, clientY, expected) => {
            expect(resolveResizeHandleDirection(edge as EditModeEdge, rect, clientX, clientY)).toBe(expected)
        })
    })

    describe('whenPressBecomesDrag', () => {
        const press = { clientX: 100, clientY: 100 } as ReactMouseEvent

        const drag = (toX: number, toY: number, buttons: number = 1): void => {
            window.dispatchEvent(new MouseEvent('mousemove', { clientX: toX, clientY: toY, buttons }))
        }

        it.each([
            ['released without moving', 100, 100],
            ['a one pixel twitch', 101, 100],
            ['just short of the threshold', 100 + EDIT_MODE_GESTURE_THRESHOLD_PX - 1, 100],
            ['just short of the threshold on the diagonal', 105, 105],
        ])('leaves %s as a click', (_case, toX, toY) => {
            const onDragStarted = jest.fn()

            whenPressBecomesDrag(press, onDragStarted)
            drag(toX, toY)
            window.dispatchEvent(new MouseEvent('mouseup'))

            expect(onDragStarted).not.toHaveBeenCalled()
        })

        it.each([
            ['horizontally', 100 + EDIT_MODE_GESTURE_THRESHOLD_PX, 100],
            ['vertically', 100, 100 + EDIT_MODE_GESTURE_THRESHOLD_PX],
            ['on the diagonal', 110, 110],
        ])('starts the drag once the pointer travels %s', (_case, toX, toY) => {
            const onDragStarted = jest.fn()

            whenPressBecomesDrag(press, onDragStarted)
            drag(toX, toY)

            expect(onDragStarted).toHaveBeenCalledTimes(1)
            const crossing = onDragStarted.mock.calls[0][0] as MouseEvent
            expect(crossing.clientX).toBe(toX)
            expect(crossing.clientY).toBe(toY)
        })

        it('starts the drag only once however far the pointer keeps moving', () => {
            const onDragStarted = jest.fn()

            whenPressBecomesDrag(press, onDragStarted)
            drag(150, 150)
            drag(200, 200)

            expect(onDragStarted).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['the button is released', () => window.dispatchEvent(new MouseEvent('mouseup'))],
            ['the release happened outside the window, so no mouseup arrived', () => drag(300, 300, 0)],
        ])('stops watching the pointer once %s', (_case, endPress) => {
            const onDragStarted = jest.fn()

            whenPressBecomesDrag(press, onDragStarted)
            endPress()
            drag(300, 300)

            expect(onDragStarted).not.toHaveBeenCalled()
        })
    })

    describe('gesture continuation', () => {
        let rafQueue: FrameRequestCallback[]
        let grid: HTMLDivElement
        let gridItem: HTMLDivElement
        let cardMeta: HTMLDivElement

        const flushFrames = (count: number = 1): void => {
            for (let i = 0; i < count; i++) {
                const callbacks = rafQueue.splice(0)
                callbacks.forEach((callback) => callback(0))
            }
        }

        const pressEvent = (target: Element, clientX: number = 150, clientY: number = 100): ReactMouseEvent =>
            ({ target, clientX, clientY, button: 0 }) as unknown as ReactMouseEvent

        const moveEvent = (clientX: number, clientY: number): MouseEvent =>
            new MouseEvent('mousemove', { clientX, clientY })

        beforeEach(() => {
            rafQueue = []
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback: FrameRequestCallback) => {
                rafQueue.push(callback)
                return rafQueue.length
            })

            grid = document.createElement('div')
            grid.className = 'react-grid-layout dashboard-view-mode'
            gridItem = document.createElement('div')
            gridItem.className = 'react-grid-item'
            gridItem.getBoundingClientRect = () => ({ ...rect, x: 0, y: 0, width: 300, height: 200 }) as DOMRect
            cardMeta = document.createElement('div')
            cardMeta.className = 'CardMeta'
            gridItem.appendChild(cardMeta)
            grid.appendChild(gridItem)
            document.body.appendChild(grid)
        })

        afterEach(() => {
            document.body.removeChild(grid)
            jest.restoreAllMocks()
        })

        const mountResizeHandle = (direction: string): HTMLSpanElement => {
            const handle = document.createElement('span')
            handle.className = `react-resizable-handle react-resizable-handle-${direction}`
            gridItem.appendChild(handle)
            return handle
        }

        it('replays the mousedown on the matching resize handle once it renders', () => {
            const onHandleMouseDown = jest.fn()

            continueResizeGestureInEditMode(pressEvent(gridItem, 150, 0), 'n', moveEvent(150, 12))
            flushFrames() // handle not rendered yet — keeps waiting

            const handle = mountResizeHandle('n')
            handle.addEventListener('mousedown', onHandleMouseDown)
            flushFrames()

            expect(onHandleMouseDown).toHaveBeenCalledTimes(1)
            const replayed = onHandleMouseDown.mock.calls[0][0] as MouseEvent
            expect(replayed.clientX).toBe(150)
            expect(replayed.clientY).toBe(0)
            expect(replayed.bubbles).toBe(true)
        })

        it('does not replay if the mouse button is released before the handle renders', () => {
            const onHandleMouseDown = jest.fn()

            continueResizeGestureInEditMode(pressEvent(gridItem, 150, 0), 'n', moveEvent(150, 12))
            window.dispatchEvent(new MouseEvent('mouseup'))

            const handle = mountResizeHandle('n')
            handle.addEventListener('mousedown', onHandleMouseDown)
            flushFrames(3)

            expect(onHandleMouseDown).not.toHaveBeenCalled()
        })

        it('gives up after the frame budget if edit mode never renders', () => {
            const onHandleMouseDown = jest.fn()

            continueResizeGestureInEditMode(pressEvent(gridItem, 150, 0), 'n', moveEvent(150, 12))
            flushFrames(15)

            const handle = mountResizeHandle('n')
            handle.addEventListener('mousedown', onHandleMouseDown)
            flushFrames(3)

            expect(onHandleMouseDown).not.toHaveBeenCalled()
        })

        it('replays the mousedown on the drag handle once the grid is in edit mode', () => {
            const onDragHandleMouseDown = jest.fn()
            cardMeta.addEventListener('mousedown', onDragHandleMouseDown)

            continueDragGestureInEditMode(pressEvent(cardMeta, 50, 20), moveEvent(62, 20))
            flushFrames() // grid still in view mode — keeps waiting
            expect(onDragHandleMouseDown).not.toHaveBeenCalled()

            grid.className = 'react-grid-layout dashboard-edit-mode'
            flushFrames()

            expect(onDragHandleMouseDown).toHaveBeenCalledTimes(1)
            const replayed = onDragHandleMouseDown.mock.calls[0][0] as MouseEvent
            expect(replayed.clientX).toBe(50)
            expect(replayed.clientY).toBe(20)
        })

        it('replays the travel that already happened so the drag starts from the press origin', () => {
            const onDragHandleMouseDown = jest.fn()
            const onDocumentMouseMove = jest.fn()
            cardMeta.addEventListener('mousedown', onDragHandleMouseDown)
            document.addEventListener('mousemove', onDocumentMouseMove)

            continueDragGestureInEditMode(pressEvent(cardMeta, 50, 20), moveEvent(80, 45))
            grid.className = 'react-grid-layout dashboard-edit-mode'
            flushFrames()
            document.removeEventListener('mousemove', onDocumentMouseMove)

            const replayedPress = onDragHandleMouseDown.mock.calls[0][0] as MouseEvent
            expect([replayedPress.clientX, replayedPress.clientY]).toEqual([50, 20])
            expect(onDocumentMouseMove).toHaveBeenCalledTimes(1)
            const replayedMove = onDocumentMouseMove.mock.calls[0][0] as MouseEvent
            expect([replayedMove.clientX, replayedMove.clientY]).toEqual([80, 45])
        })
    })
})
