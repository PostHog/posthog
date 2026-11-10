import { renderHook } from '@testing-library/react'

import { useClickToMoveTile } from './useClickToMoveTile'

describe('useClickToMoveTile', () => {
    let container: HTMLElement
    let gridItem: HTMLElement
    let handle: HTMLElement

    beforeEach(() => {
        jest.useFakeTimers()
        document.body.innerHTML = `
            <div class="container">
                <div class="react-grid-layout">
                    <div class="react-grid-item"><div class="CardMeta"><span class="title">Signups</span></div></div>
                </div>
            </div>`
        container = document.querySelector('.container')!
        gridItem = document.querySelector('.react-grid-item')!
        handle = document.querySelector('.title')!
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    const renderMove = (enabled = true): { onCarryingChange: jest.Mock; rerender: (enabled: boolean) => void } => {
        const onCarryingChange = jest.fn()
        const props = (isEnabled: boolean): Parameters<typeof useClickToMoveTile>[0] => ({
            containerRef: { current: container },
            enabled: isEnabled,
            handleSelector: '.CardMeta',
            cancelSelector: 'button',
            onCarryingChange,
        })
        const { result, rerender } = renderHook((isEnabled: boolean) => useClickToMoveTile(props(isEnabled)), {
            initialProps: enabled,
        })
        // react-grid-layout reports a drag start on the first pointer move, not on the press.
        document.addEventListener('mousemove', () => result.current.carryHeldDrag(gridItem), { once: true })
        return { onCarryingChange, rerender }
    }

    const pickUpWithClick = (): void => {
        handle.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 10, clientY: 10 }))
        handle.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 10, clientY: 10 }))
        document.body.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 40, clientY: 40 }))
    }

    it('drops a clicked tile on the next click, even though its replayed press starts a drag too', () => {
        const { onCarryingChange } = renderMove()
        pickUpWithClick()
        expect(onCarryingChange).toHaveBeenLastCalledWith(true)

        document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
        document.body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }))
        jest.runOnlyPendingTimers()
        const nextPress = new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 })
        document.body.dispatchEvent(nextPress)

        expect(onCarryingChange).toHaveBeenLastCalledWith(false)
        expect(nextPress.defaultPrevented).toBe(false)
    })

    it('puts a carried tile back and stops swallowing presses when edit mode ends', () => {
        const { onCarryingChange, rerender } = renderMove()
        pickUpWithClick()

        rerender(false)
        const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 })
        document.body.dispatchEvent(press)

        expect(onCarryingChange).toHaveBeenLastCalledWith(false)
        expect(press.defaultPrevented).toBe(false)
    })
})
