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

    // Each case builds the surface from the marker it really carries in the DOM: the drag/resize
    // cases use the classes react-grid-layout puts on a tile mid-gesture ("react-draggable-dragging",
    // and "resizing" alongside "react-grid-item"); the menu cases use the Radix class and the quill
    // data-slot attributes emitted by dashboard-reachable dropdowns, menu bars, and popovers.
    it.each([
        ['a LemonModal overlay', '<div class="LemonModal__overlay"></div>'],
        ['a Popover', '<div class="Popover"></div>'],
        ['an active drag', '<div class="react-grid-item react-draggable-dragging"></div>'],
        ['an active resize', '<div class="react-grid-item resizing"></div>'],
        ['a Radix dropdown menu', '<div class="primitive-menu-content"></div>'],
        ['a quill menu bar menu', '<div data-slot="menubar-content"></div>'],
        ['a quill popover', '<div data-slot="popover-content"></div>'],
    ])('defers a bare Escape to %s instead of firing the shortcut', async (_label, html) => {
        const callback = jest.fn()
        await registerEscapeShortcut(callback)

        document.body.insertAdjacentHTML('beforeend', html)

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
