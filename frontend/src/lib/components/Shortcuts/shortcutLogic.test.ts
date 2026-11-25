import { initKeaTests } from '~/test/init'

import { shortcutLogic } from './shortcutLogic'

function pressKey(key: string): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('shortcutLogic key handling', () => {
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

    it('fires a single-key shortcut when the key does not continue the sequence in progress', () => {
        const onOther = jest.fn()
        logic.actions.registerShortcut({
            name: 'Other',
            keybind: [['x']],
            intent: 'Other',
            interaction: 'function',
            callback: onOther,
        })

        pressKey('h')
        pressKey('x')

        expect(onOther).toHaveBeenCalledTimes(1)
        expect(onSequence).not.toHaveBeenCalled()
    })

    it.each([
        { target: 'a text field', editable: true },
        { target: 'the page', editable: false },
    ])('ignores a keydown with no key on $target, like the one browser autofill sends', ({ editable }) => {
        const errors: unknown[] = []
        const onError = (event: ErrorEvent): void => {
            errors.push(event.error)
            event.preventDefault()
        }
        window.addEventListener('error', onError)
        const input = document.createElement('input')
        document.body.appendChild(input)

        const target = editable ? input : document.body
        target.dispatchEvent(new Event('keydown', { bubbles: true }))
        pressKey('e')

        input.remove()
        window.removeEventListener('error', onError)
        expect(errors).toEqual([])
        expect(onSingleKey).toHaveBeenCalledTimes(1)
    })

    it.each([
        { matchInEditable: true, expectedCalls: 1 },
        { matchInEditable: false, expectedCalls: 0 },
    ])(
        'fires a sequence typed into a text field only when matchInEditable is $matchInEditable',
        ({ matchInEditable, expectedCalls }) => {
            const onTyped = jest.fn()
            logic.actions.registerShortcut({
                name: 'Typed',
                keybind: [['h', 'then', 'e', 'then', 'y']],
                intent: 'Easter egg',
                interaction: 'function',
                matchInEditable,
                callback: onTyped,
            })
            const input = document.createElement('input')
            document.body.appendChild(input)

            const events = ['x', 'H', 'e', 'y'].map(
                (key) => new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
            )
            events.forEach((event) => input.dispatchEvent(event))
            input.remove()

            expect(onTyped).toHaveBeenCalledTimes(expectedCalls)
            expect(onSingleKey).not.toHaveBeenCalled()
            expect(events.some((event) => event.defaultPrevented)).toBe(false)
        }
    )

    it.each([
        { interruption: 'a pause longer than the sequence timeout' },
        { interruption: 'switching to another text field' },
        { interruption: 'a ctrl chord' },
        { interruption: 'a key inside a data-shortcuts-ignore region' },
    ])('does not fire a sequence typed into a text field across $interruption', ({ interruption }) => {
        const onTyped = jest.fn()
        logic.actions.registerShortcut({
            name: 'Typed',
            keybind: [['h', 'then', 'e', 'then', 'y']],
            intent: 'Easter egg',
            interaction: 'function',
            matchInEditable: true,
            callback: onTyped,
        })
        const first = document.createElement('input')
        const second = document.createElement('input')
        const ignored = document.createElement('div')
        ignored.dataset.shortcutsIgnore = 'all'
        ignored.appendChild(document.createElement('input'))
        document.body.append(first, second, ignored)
        const typeInto = (target: Element, key: string, init: KeyboardEventInit = {}): void => {
            target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
        }

        typeInto(first, 'h')
        let rest: Element = first
        if (interruption === 'a pause longer than the sequence timeout') {
            jest.setSystemTime(new Date('2026-01-01T00:00:02Z'))
        } else if (interruption === 'switching to another text field') {
            rest = second
        } else if (interruption === 'a ctrl chord') {
            typeInto(first, 'v', { ctrlKey: true })
        } else {
            typeInto(ignored.firstElementChild!, 'x')
        }
        typeInto(rest, 'e')
        typeInto(rest, 'y')
        first.remove()
        second.remove()
        ignored.remove()

        expect(onTyped).not.toHaveBeenCalled()
    })
})

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

    it('leaves hidden shortcuts out of the search items', () => {
        shortcutLogic.actions.registerShortcut({
            name: 'visible-action',
            keybind: [['e']],
            intent: 'Visible action',
            interaction: 'function',
            callback: jest.fn(),
        })
        shortcutLogic.actions.registerShortcut({
            name: 'hidden-action',
            keybind: [['h', 'then', 'e', 'then', 's']],
            intent: 'Hidden action',
            interaction: 'function',
            hidden: true,
            callback: jest.fn(),
        })

        expect(shortcutLogic.values.shortcutItems.map((item) => item.name)).toEqual(['Visible action'])
    })
})
