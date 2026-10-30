import { initKeaTests } from '~/test/init'

import { shortcutLogic } from './shortcutLogic'

describe('shortcutLogic', () => {
    beforeEach(() => {
        initKeaTests()
        shortcutLogic.mount()
    })

    afterEach(() => {
        shortcutLogic.unmount()
    })

    it('turns enabled shortcuts into executable search items', () => {
        const callback = jest.fn()
        shortcutLogic.actions.registerShortcut({
            name: 'staff-only-action',
            keybind: [['command', 'shift', 'p']],
            intent: 'Open staff action',
            interaction: 'function',
            callback,
        })
        shortcutLogic.actions.registerShortcut({
            name: 'disabled-action',
            keybind: [['command', 'shift', 'd']],
            intent: 'Disabled action',
            interaction: 'function',
            callback: jest.fn(),
        })
        shortcutLogic.actions.toggleShortcutDisabled('disabled-action')
        for (const name of ['Search', 'SQLEditor']) {
            shortcutLogic.actions.registerShortcut({
                name,
                keybind: [['command', 'k']],
                intent: name,
                interaction: 'function',
                callback: jest.fn(),
            })
        }

        expect(shortcutLogic.values.shortcutItems.map((item) => item.name)).toEqual(['Open staff action'])
        expect(shortcutLogic.values.shortcutItems[0].keybinding).toBeTruthy()
        shortcutLogic.values.shortcutItems[0].onSelect?.()
        expect(callback).toHaveBeenCalledTimes(1)
    })
})
