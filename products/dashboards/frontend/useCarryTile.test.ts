import { renderHook } from '@testing-library/react'

import { useCarryTile } from './useCarryTile'

describe('useCarryTile', () => {
    let container: HTMLElement
    let gridItem: HTMLElement
    let handle: HTMLElement
    let resizeHandle: HTMLElement

    beforeEach(() => {
        jest.useFakeTimers()
        document.body.innerHTML = `
            <div class="container">
                <div class="react-grid-layout">
                    <div class="react-grid-item">
                        <div class="CardMeta"><span class="title">Signups</span></div>
                        <span class="react-resizable-handle react-resizable-handle-se"></span>
                    </div>
                </div>
            </div>`
        container = document.querySelector('.container')!
        gridItem = document.querySelector('.react-grid-item')!
        handle = document.querySelector('.title')!
        resizeHandle = document.querySelector('.react-resizable-handle')!
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    const renderMove = (
        enabled = true,
        gesture: 'move' | 'resize' = 'move'
    ): {
        onCarryingChange: jest.Mock
        onCarryCanceled: jest.Mock
        rerender: (enabled: boolean) => void
        result: { current: ReturnType<typeof useCarryTile> }
    } => {
        const onCarryingChange = jest.fn()
        const onCarryCanceled = jest.fn()
        const props = (isEnabled: boolean): Parameters<typeof useCarryTile>[0] => ({
            containerRef: { current: container },
            enabled: isEnabled,
            handleSelector: '.CardMeta',
            cancelSelector: 'button',
            onCarryingChange,
            onCarryCanceled,
        })
        const { result, rerender } = renderHook((isEnabled: boolean) => useCarryTile(props(isEnabled)), {
            initialProps: enabled,
        })
        if (gesture === 'move') {
            // react-grid-layout reports a drag start on the first pointer move, not on the press.
            document.addEventListener('mousemove', () => result.current.carryHeld(gridItem, 'move'), { once: true })
        } else {
            // react-resizable reports a resize start on the press itself.
            resizeHandle.addEventListener('mousedown', () => result.current.carryHeld(resizeHandle, 'resize'), {
                once: true,
            })
        }
        return { onCarryingChange, onCarryCanceled, rerender, result }
    }

    const pickUpWithClick = (): void => {
        handle.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 10, clientY: 10 }))
        handle.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 10, clientY: 10 }))
        document.body.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 40, clientY: 40 }))
    }

    it('drops a clicked tile on the next click, even though its replayed press starts a drag too', () => {
        const { onCarryingChange } = renderMove()
        pickUpWithClick()
        expect(onCarryingChange).toHaveBeenLastCalledWith('move')

        document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
        document.body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }))
        jest.runOnlyPendingTimers()
        const nextPress = new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 })
        document.body.dispatchEvent(nextPress)

        expect(onCarryingChange).toHaveBeenLastCalledWith(null)
        expect(nextPress.defaultPrevented).toBe(false)
    })

    it('puts a carried tile back and stops swallowing presses when edit mode ends', () => {
        const { onCarryingChange, rerender } = renderMove()
        pickUpWithClick()

        rerender(false)
        const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 })
        document.body.dispatchEvent(press)

        expect(onCarryingChange).toHaveBeenLastCalledWith(null)
        expect(press.defaultPrevented).toBe(false)
    })

    it.each([
        { name: 'clicked', releaseAt: 11, input: 'click' },
        { name: 'dragged', releaseAt: 60, input: 'drag' },
    ])('keeps resizing a tile after its handle is $name until the next click', ({ releaseAt, input }) => {
        const { onCarryingChange, result } = renderMove(true, 'resize')
        const resizeReleases: MouseEvent[] = []
        document.addEventListener('mouseup', (event) => resizeReleases.push(event))

        resizeHandle.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 10, clientY: 10 }))
        document.body.dispatchEvent(
            new MouseEvent('mouseup', { bubbles: true, cancelable: true, button: 0, clientX: releaseAt, clientY: 10 })
        )
        expect(onCarryingChange).toHaveBeenLastCalledWith('resize')
        expect(resizeReleases).toHaveLength(0)

        document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
        document.body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }))

        expect(resizeReleases).toHaveLength(1)
        expect(result.current.tileCarryInputRef.current).toBe(input)
        expect(onCarryingChange).toHaveBeenLastCalledWith(null)
    })

    it.each([
        { kind: 'move' as const, target: (): HTMLElement => gridItem },
        { kind: 'resize' as const, target: (): HTMLElement => resizeHandle },
    ])('does not carry a $kind started by touch after an earlier mouse press', ({ kind, target }) => {
        const { onCarryingChange, result } = renderMove(true, kind)
        handle.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 10, clientY: 10 }))
        handle.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0, clientX: 10, clientY: 10 }))

        target().dispatchEvent(new Event('touchstart', { bubbles: true }))
        result.current.carryHeld(target(), kind)
        target().dispatchEvent(new Event('touchend', { bubbles: true }))
        const nextRelease = new MouseEvent('mouseup', { bubbles: true, cancelable: true, button: 0 })
        document.body.dispatchEvent(nextRelease)

        expect(onCarryingChange).not.toHaveBeenCalled()
        expect(nextRelease.defaultPrevented).toBe(false)
    })

    it('puts a carried resize back to where it started on Escape', () => {
        const { onCarryingChange, onCarryCanceled, result } = renderMove(true, 'resize')
        const atRelease: [string, unknown[][]][] = []
        document.addEventListener('mouseup', () =>
            atRelease.push([result.current.tileCarryInputRef.current, [...onCarryCanceled.mock.calls]])
        )

        resizeHandle.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 10, clientY: 10 }))
        document.body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, button: 0 }))
        document.body.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'Escape' }))

        // The grid settles the resize on this release, so it must already know the resize was canceled.
        expect(atRelease).toEqual([['canceled', [['resize']]]])
        expect(onCarryingChange).toHaveBeenLastCalledWith(null)
    })
})
