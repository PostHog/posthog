import { cleanup, renderHook } from '@testing-library/react'

import posthog from 'lib/posthog-typed'

import { useKeyboardHotkeys } from './useKeyboardHotkeys'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { __loaded: true, capture: jest.fn() },
}))

const mockPosthog = posthog as unknown as { __loaded: boolean; capture: jest.Mock }

function press(key: string, init: KeyboardEventInit = {}, target: Element = document.body): void {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...init }))
}

describe('useKeyboardHotkeys', () => {
    beforeEach(() => {
        mockPosthog.__loaded = true
        mockPosthog.capture.mockClear()
    })

    afterEach(() => {
        // RTL auto-cleanup doesn't run in this jest setup - unmount so window keydown listeners don't leak between tests
        cleanup()
    })

    it('runs the action and captures keybind triggered on a match', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ k: { action } }))

        press('k')

        expect(action).toHaveBeenCalledTimes(1)
        expect(mockPosthog.capture).toHaveBeenCalledTimes(1)
        expect(mockPosthog.capture).toHaveBeenCalledWith('keybind triggered', {
            keybind: 'k',
            mechanism: 'hotkey',
        })
    })

    it('captures the normalized key name for space', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ space: { action } }))

        press(' ')

        expect(action).toHaveBeenCalledTimes(1)
        expect(mockPosthog.capture).toHaveBeenCalledWith('keybind triggered', {
            keybind: 'space',
            mechanism: 'hotkey',
        })
    })

    it('captures shift chords for hotkeys that do not handle modifiers themselves', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ k: { action } }))

        press('K', { shiftKey: true })

        expect(action).toHaveBeenCalledTimes(1)
        expect(mockPosthog.capture).toHaveBeenCalledWith('keybind triggered', {
            keybind: 'shift+k',
            mechanism: 'hotkey',
        })
    })

    it('captures modifiers in the same order as shortcutLogic (shift before option)', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ arrowleft: { action, willHandleEvent: true } }))

        press('ArrowLeft', { shiftKey: true, altKey: true })

        expect(action).toHaveBeenCalledTimes(1)
        expect(mockPosthog.capture).toHaveBeenCalledWith('keybind triggered', {
            keybind: 'shift+option+arrowleft',
            mechanism: 'hotkey',
        })
    })

    it('does not capture held-key repeats but still runs the action', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ arrowleft: { action, willHandleEvent: true } }))

        press('ArrowLeft')
        press('ArrowLeft', { repeat: true })
        press('ArrowLeft', { repeat: true })

        expect(action).toHaveBeenCalledTimes(3)
        expect(mockPosthog.capture).toHaveBeenCalledTimes(1)
    })

    it.each([{ metaKey: true }, { ctrlKey: true }])(
        'does not capture ctrl/meta chords on willHandleEvent hotkeys, whose actions treat them as browser shortcuts and no-op (%o)',
        (modifiers) => {
            const action = jest.fn()
            renderHook(() => useKeyboardHotkeys({ arrowleft: { action, willHandleEvent: true } }))

            press('ArrowLeft', modifiers)

            expect(action).toHaveBeenCalledTimes(1)
            expect(mockPosthog.capture).not.toHaveBeenCalled()
        }
    )

    it('does not run or capture modifier chords for hotkeys that do not handle events', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ k: { action } }))

        press('k', { metaKey: true })
        press('k', { ctrlKey: true })
        press('k', { altKey: true })

        expect(action).not.toHaveBeenCalled()
        expect(mockPosthog.capture).not.toHaveBeenCalled()
    })

    it('does not capture when posthog is uninitialized, as in the toolbar bundle on customer sites', () => {
        mockPosthog.__loaded = false
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ escape: { action, willHandleEvent: true } }))

        press('Escape')

        expect(action).toHaveBeenCalledTimes(1)
        expect(mockPosthog.capture).not.toHaveBeenCalled()
    })

    it('does not run or capture disabled hotkeys', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ k: { action, disabled: true } }))

        press('k')

        expect(action).not.toHaveBeenCalled()
        expect(mockPosthog.capture).not.toHaveBeenCalled()
    })

    it('does not run or capture while typing in an input', () => {
        const action = jest.fn()
        renderHook(() => useKeyboardHotkeys({ k: { action } }))

        const input = document.createElement('input')
        document.body.appendChild(input)
        press('k', {}, input)
        input.remove()

        expect(action).not.toHaveBeenCalled()
        expect(mockPosthog.capture).not.toHaveBeenCalled()
    })
})
