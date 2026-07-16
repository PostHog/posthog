import { initKeaTests } from '~/test/init'

import { shortcutLogic } from './shortcutLogic'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { __loaded: true, capture: jest.fn() },
}))

// The ⌘⌥ matching path branches on isMac(), which is captured once at module load.
jest.mock('lib/utils/dom', () => ({
    ...jest.requireActual('lib/utils/dom'),
    isMac: () => true,
}))

describe('shortcutLogic', () => {
    let logic: ReturnType<typeof shortcutLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = shortcutLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    function register(name: string, keybind: string[][]): jest.Mock {
        const callback = jest.fn()
        logic.actions.registerShortcut({ name, keybind, intent: name, interaction: 'function', callback })
        return callback
    }

    function press(init: KeyboardEventInit): void {
        window.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, ...init }))
    }

    it('matches ⌘⌥ shortcuts by the layout-aware key, not the physical key position', () => {
        const onC = register('c-action', [['command', 'option', 'c']])
        const onI = register('i-action', [['command', 'option', 'i']])

        // On Dvorak the key labelled "c" sits where QWERTY has "i": event.code is "KeyI"
        // but event.key is the true letter "c". Matching must follow the letter, not the position.
        press({ key: 'c', code: 'KeyI', metaKey: true, altKey: true })

        expect(onC).toHaveBeenCalledTimes(1)
        expect(onI).not.toHaveBeenCalled()
    })

    it('falls back to the physical key only when Option turns event.key into a non-letter glyph', () => {
        const onK = register('k-action', [['command', 'option', 'k']])

        // macOS US layout: ⌥K produces the glyph "˚" as event.key, so the physical code is the
        // only reliable source of the intended letter.
        press({ key: '˚', code: 'KeyK', metaKey: true, altKey: true })

        expect(onK).toHaveBeenCalledTimes(1)
    })
})
