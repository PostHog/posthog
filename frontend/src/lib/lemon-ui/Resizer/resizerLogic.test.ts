import { initKeaTests } from '~/test/init'

import { resizerLogic } from './resizerLogic'

describe('resizerLogic', () => {
    let logic: ReturnType<typeof resizerLogic.build>
    let container: HTMLDivElement
    let onToggleClosed: jest.Mock

    beforeEach(() => {
        initKeaTests(false)
        jest.useFakeTimers()
        container = document.createElement('div')
        jest.spyOn(container, 'getBoundingClientRect').mockReturnValue({ width: 300, height: 400 } as DOMRect)
        onToggleClosed = jest.fn()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    function mount(): void {
        logic = resizerLogic({
            logicKey: 'test-resizer',
            placement: 'right',
            containerRef: { current: container },
            closeThreshold: 100,
            onToggleClosed,
        })
        logic.mount()
    }

    function mouse(type: 'mousemove' | 'mouseup', coordinate: number): void {
        const event = new MouseEvent(type, { clientX: coordinate, clientY: coordinate, button: 0 })
        Object.defineProperties(event, { pageX: { value: coordinate }, pageY: { value: coordinate } })
        document.dispatchEvent(event)
    }

    it('uses the latest pointer position per frame and saves the release position', () => {
        mount()
        logic.actions.beginResize(0)

        mouse('mousemove', 10)
        mouse('mousemove', 20)
        expect(logic.values.desiredSize).toBeNull()

        jest.advanceTimersByTime(16)
        expect(logic.values.desiredSize).toBe(320)

        mouse('mousemove', 30)
        mouse('mouseup', 40)
        expect(logic.values.size).toBe(340)
        expect(logic.values.isResizeInProgress).toBe(false)
        jest.advanceTimersByTime(16)
        expect(logic.values.resizingSize).toBeNull()
    })

    it('keeps the saved width when released past the collapse threshold before the next frame', () => {
        mount()
        logic.actions.setDesiredSize(300)
        logic.actions.beginResize(300)

        mouse('mousemove', 90)
        mouse('mouseup', 80)

        expect(onToggleClosed).toHaveBeenCalledWith(true)
        expect(logic.values.size).toBe(300)
        expect(logic.values.isResizeInProgress).toBe(false)
        jest.advanceTimersByTime(16)
        expect(logic.values.resizingSize).toBeNull()
    })

    it.each(['endResize', 'unmount'] as const)('cancels a pending frame on %s', (end) => {
        mount()
        logic.actions.setDesiredSize(300)
        logic.actions.beginResize(300)
        mouse('mousemove', 90)

        if (end === 'unmount') {
            logic.unmount()
            logic.mount()
            logic.actions.setDesiredSize(300)
        } else {
            logic.actions.endResize()
        }

        jest.advanceTimersByTime(16)
        mouse('mousemove', 80)
        mouse('mouseup', 80)
        jest.advanceTimersByTime(16)

        expect(onToggleClosed).not.toHaveBeenCalled()
        expect(logic.values.desiredSize).toBe(300)
        expect(logic.values.resizingSize).toBeNull()
        expect(logic.values.isResizeInProgress).toBe(false)
        expect(document.body.classList.contains('is-resizing')).toBe(false)
    })
})
