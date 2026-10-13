import { initKeaTests } from '~/test/init'

import { shortcutLogic } from './shortcutLogic'

function pressKey(key: string): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('shortcutLogic', () => {
    let logic: ReturnType<typeof shortcutLogic.build>
    let onSingleKey: jest.Mock
    let onSequence: jest.Mock

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-01-01T00:00:00Z'))

        initKeaTests()
        logic = shortcutLogic()
        logic.mount()

        onSingleKey = jest.fn()
        onSequence = jest.fn()
        logic.actions.registerShortcut({
            name: 'Edit',
            keybind: [['e']],
            intent: 'Edit',
            interaction: 'function',
            callback: onSingleKey,
        })
        logic.actions.registerShortcut({
            name: 'Hesoyam',
            keybind: [['h', 'then', 'e', 'then', 's']],
            intent: 'Easter egg',
            interaction: 'function',
            callback: onSequence,
        })
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('completes a sequence whose intermediate key is also a single-key shortcut', () => {
        pressKey('h')
        pressKey('e')
        pressKey('s')

        expect(onSequence).toHaveBeenCalledTimes(1)
        expect(onSingleKey).not.toHaveBeenCalled()
    })

    it('fires a single-key shortcut once an abandoned sequence has timed out', () => {
        pressKey('h')
        jest.setSystemTime(new Date('2026-01-01T00:00:02Z'))

        pressKey('e')

        expect(onSingleKey).toHaveBeenCalledTimes(1)
        expect(onSequence).not.toHaveBeenCalled()
    })
})
