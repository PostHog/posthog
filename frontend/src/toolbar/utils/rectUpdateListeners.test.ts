import type { DisposableFunction, DisposablesManager, SetupFunction } from '~/kea-disposables'
import { addRectUpdateListeners } from '~/toolbar/utils/rectUpdateListeners'

describe('addRectUpdateListeners', () => {
    let frames: FrameRequestCallback[]
    let disposables: DisposablesManager
    let cleanup: DisposableFunction

    const runPendingFrames = (): void => {
        const pending = frames
        frames = []
        pending.forEach((callback) => callback(0))
    }

    beforeEach(() => {
        frames = []
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback: FrameRequestCallback) => {
            frames.push(callback)
            return frames.length
        })
        jest.spyOn(window, 'cancelAnimationFrame').mockImplementation((handle: number) => {
            frames[handle - 1] = () => {}
        })
        disposables = {
            add: (setup: SetupFunction) => {
                cleanup = setup()
            },
        } as unknown as DisposablesManager
    })

    afterEach(() => {
        cleanup?.()
        jest.restoreAllMocks()
    })

    it('does not run the callback on the stack that dispatched the event', () => {
        const onFrame = jest.fn()
        addRectUpdateListeners(disposables, onFrame)

        window.dispatchEvent(new Event('resize'))
        expect(onFrame).not.toHaveBeenCalled()

        runPendingFrames()
        expect(onFrame).toHaveBeenCalledTimes(1)
    })

    it('coalesces a burst of scroll and resize events into one call per frame', () => {
        const onFrame = jest.fn()
        addRectUpdateListeners(disposables, onFrame)

        document.dispatchEvent(new Event('scroll'))
        document.dispatchEvent(new Event('scroll'))
        window.dispatchEvent(new Event('resize'))
        runPendingFrames()
        expect(onFrame).toHaveBeenCalledTimes(1)

        window.dispatchEvent(new Event('resize'))
        runPendingFrames()
        expect(onFrame).toHaveBeenCalledTimes(2)
    })

    it('drops a pending frame and stops listening once disposed', () => {
        const onFrame = jest.fn()
        addRectUpdateListeners(disposables, onFrame)

        window.dispatchEvent(new Event('resize'))
        cleanup()
        runPendingFrames()
        expect(onFrame).not.toHaveBeenCalled()

        window.dispatchEvent(new Event('resize'))
        runPendingFrames()
        expect(onFrame).not.toHaveBeenCalled()
    })
})
