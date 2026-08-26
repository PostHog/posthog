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

    const pressEscape = (): void => {
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
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

    it('triggers a bare Escape shortcut when nothing is open', async () => {
        const callback = jest.fn()
        await registerEscapeShortcut(callback)

        pressEscape()

        expect(callback).toHaveBeenCalledTimes(1)
    })

    it.each([['.LemonModal__overlay'], ['.Popover'], ['.react-draggable-dragging'], ['.react-resizable-resizing']])(
        'defers a bare Escape to an open %s instead of firing the shortcut',
        async (selector) => {
            const callback = jest.fn()
            await registerEscapeShortcut(callback)

            const overlay = document.createElement('div')
            overlay.className = selector.slice(1)
            document.body.appendChild(overlay)

            pressEscape()

            expect(callback).not.toHaveBeenCalled()
        }
    )
})
