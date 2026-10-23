import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { createRef } from 'react'
import { DraggableCore } from 'react-draggable'

describe('drag selection suppression', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
    })

    it.each(['release', 'unmount'])('restores text selection after %s without changing body styles', (end) => {
        const nodeRef = createRef<HTMLDivElement>()
        const { getByTestId, unmount } = render(
            <DraggableCore nodeRef={nodeRef}>
                <div ref={nodeRef} data-attr="drag-target">
                    Selectable text
                </div>
            </DraggableCore>
        )
        const target = getByTestId('drag-target')
        const beforeDrag = new Event('selectstart', { bubbles: true, cancelable: true })
        fireEvent(target, beforeDrag)
        expect(beforeDrag.defaultPrevented).toBe(false)

        fireEvent.mouseDown(target, { button: 0, clientX: 10, clientY: 10 })
        const duringDrag = new Event('selectstart', { bubbles: true, cancelable: true })
        fireEvent(target, duringDrag)
        expect(duringDrag.defaultPrevented).toBe(true)
        expect(document.body.classList.contains('react-draggable-transparent-selection')).toBe(false)

        if (end === 'release') {
            fireEvent.mouseUp(document, { button: 0, clientX: 20, clientY: 20 })
        } else {
            unmount()
        }
        act(() => jest.runOnlyPendingTimers())

        const afterDrag = new Event('selectstart', { bubbles: true, cancelable: true })
        fireEvent(document, afterDrag)
        expect(afterDrag.defaultPrevented).toBe(false)
    })
})
