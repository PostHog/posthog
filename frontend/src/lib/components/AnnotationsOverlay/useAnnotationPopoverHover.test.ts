import { act, fireEvent, renderHook } from '@testing-library/react'

import { useAnnotationPopoverHover } from './useAnnotationPopoverHover'

describe('useAnnotationPopoverHover', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('keeps the popup open on the path from the badge and closes after leaving it', () => {
        const onLeave = jest.fn()
        const { result } = renderHook(() => useAnnotationPopoverHover(onLeave))
        const popup = document.createElement('div')
        jest.spyOn(popup, 'getBoundingClientRect').mockReturnValue({
            left: 100,
            right: 300,
            top: 100,
            bottom: 200,
        } as DOMRect)
        result.current.popupRef.current = popup

        act(() => result.current.start({ x: 150, y: 250 }))
        act(() => jest.advanceTimersByTime(300))
        fireEvent.mouseMove(document, { clientX: 160, clientY: 225 })
        act(() => jest.advanceTimersByTime(300))
        expect(onLeave).not.toHaveBeenCalled()

        act(() => result.current.cancel())
        act(() => jest.runOnlyPendingTimers())
        expect(onLeave).not.toHaveBeenCalled()

        act(() => result.current.leavePopup())
        expect(onLeave).toHaveBeenCalledTimes(1)

        act(() => result.current.start({ x: 150, y: 250 }))
        fireEvent.mouseMove(document, { clientX: 400, clientY: 225 })
        expect(onLeave).toHaveBeenCalledTimes(2)

        act(() => result.current.start({ x: 150, y: 250 }))
        act(() => jest.runOnlyPendingTimers())
        expect(onLeave).toHaveBeenCalledTimes(3)
    })
})
