import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { shortcutLogic } from './shortcutLogic'
import { ShortcutMenu } from './ShortcutMenu'

describe('ShortcutMenu', () => {
    afterEach(() => {
        cleanup()
    })

    it('lists visible shortcuts but not hidden ones', () => {
        initKeaTests()
        const logic = shortcutLogic()
        logic.mount()

        logic.actions.registerShortcut({
            name: 'Edit',
            keybind: [['e']],
            intent: 'Edit',
            interaction: 'function',
            callback: jest.fn(),
        })
        logic.actions.registerShortcut({
            name: 'Hesoyam',
            keybind: [['h', 'then', 'e', 'then', 's']],
            intent: 'Easter egg',
            interaction: 'function',
            hidden: true,
            callback: jest.fn(),
        })
        logic.actions.setShortcutMenuOpen(true)

        render(<ShortcutMenu />)

        expect(document.querySelector('[data-shortcut-name="Edit"]')).not.toBeNull()
        expect(document.querySelector('[data-shortcut-name="Hesoyam"]')).toBeNull()

        logic.unmount()
    })
})
