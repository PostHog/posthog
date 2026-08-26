import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { shortcutLogic } from './shortcutLogic'

describe('shortcutLogic', () => {
    let logic: ReturnType<typeof shortcutLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = shortcutLogic()
        logic.mount()
    })

    afterEach(() => {
        document.body.innerHTML = ''
        logic.unmount()
    })

    const pressKey = (key: string): void => {
        window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
    }

    const pressEscape = (): void => {
        pressKey('Escape')
    }

    const registerEscapeShortcut = async (callback: () => void): Promise<void> => {
        await expectLogic(logic, () => {
            logic.actions.registerShortcut({
                name: 'CancelEdit',
                keybind: [['escape']],
                intent: 'Cancel edit mode',
                interaction: 'function',
                callback,
            })
        }).toFinishAllListeners()
    }

    const registerSequenceShortcut = async (name: string, keybind: string[], callback: () => void): Promise<void> => {
        await expectLogic(logic, () => {
            logic.actions.registerShortcut({
                name,
                keybind: [keybind],
                intent: 'Sequence shortcut',
                interaction: 'function',
                callback,
            })
        }).toFinishAllListeners()
    }

    it('triggers a bare Escape shortcut when nothing is open', async () => {
        const callback = jest.fn()
        await registerEscapeShortcut(callback)

        pressEscape()

        expect(callback).toHaveBeenCalledTimes(1)
    })

    // The last two cases use the classes react-grid-layout actually puts on a tile mid-gesture:
    // "react-draggable-dragging" while dragging and "resizing" (alongside "react-grid-item") while resizing.
    it.each([
        ['a LemonModal overlay', 'LemonModal__overlay'],
        ['a Popover', 'Popover'],
        ['an active drag', 'react-grid-item react-draggable-dragging'],
        ['an active resize', 'react-grid-item resizing'],
    ])('defers a bare Escape to %s instead of firing the shortcut', async (_label, className) => {
        const callback = jest.fn()
        await registerEscapeShortcut(callback)

        const overlay = document.createElement('div')
        overlay.className = className
        document.body.appendChild(overlay)

        pressEscape()

        expect(callback).not.toHaveBeenCalled()
    })

    it('clears an in-progress sequence when a bare Escape defers to an overlay', async () => {
        const escapeCallback = jest.fn()
        const sequenceCallback = jest.fn()
        // Escape is only a single-key shortcut in dashboard edit mode; that is the only place the
        // deferred Escape can skip the sequence reset it would otherwise get from the no-match branch.
        await registerEscapeShortcut(escapeCallback)
        await registerSequenceShortcut('ProjectSwitcher', ['g', 'then', 'p'], sequenceCallback)

        const overlay = document.createElement('div')
        overlay.className = 'Popover'
        document.body.appendChild(overlay)

        pressKey('g') // starts the "g then p" sequence
        pressEscape() // defers to the overlay, and must reset the sequence
        pressKey('p') // must not complete the now-stale sequence

        expect(escapeCallback).not.toHaveBeenCalled()
        expect(sequenceCallback).not.toHaveBeenCalled()
    })
})
