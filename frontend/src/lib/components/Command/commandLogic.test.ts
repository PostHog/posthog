import { initKeaTests } from '~/test/init'

import { commandLogic } from './commandLogic'

describe('commandLogic', () => {
    let logic: ReturnType<typeof commandLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = commandLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the palette opening when the shortcut is pressed again before the input is ready', () => {
        logic.actions.toggleCommand('keyboard-shortcut')
        logic.actions.toggleCommand('keyboard-shortcut')
        expect(logic.values.isCommandOpen).toBe(true)

        logic.actions.commandInputReady()
        logic.actions.toggleCommand('keyboard-shortcut')
        expect(logic.values.isCommandOpen).toBe(false)
    })

    it('holds keys typed before the input is ready and stops at Escape', () => {
        const pageInput = document.createElement('input')
        document.body.append(pageInput)
        pageInput.focus()
        logic.actions.toggleCommand('keyboard-shortcut')

        for (const key of ['d', 'a', 's', 'h']) {
            pageInput.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
        }
        expect(logic.values.pendingText).toBe('dash')

        pageInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
        expect(logic.values.isCommandOpen).toBe(false)
        pageInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true }))
        expect(logic.values.pendingText).toBe('')
        pageInput.remove()
    })
})
