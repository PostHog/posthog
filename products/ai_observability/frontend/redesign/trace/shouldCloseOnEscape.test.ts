import { shouldCloseOnEscape } from './shouldCloseOnEscape'

describe('shouldCloseOnEscape', () => {
    afterEach(() => {
        document.body.innerHTML = ''
    })

    function pressKey(key: string, targetHtml: string, targetSelector: string): KeyboardEvent {
        document.body.innerHTML = targetHtml
        const event = new KeyboardEvent('keydown', { key, bubbles: true })
        document.querySelector(targetSelector)?.dispatchEvent(event)
        return event
    }

    it.each([
        ['Escape on the page', 'Escape', '<button id="t"></button>', true],
        ['another key', 'ArrowDown', '<button id="t"></button>', false],
        ['Escape in an input', 'Escape', '<input id="t" />', false],
        ['Escape in a textarea', 'Escape', '<textarea id="t"></textarea>', false],
        ['Escape in a contenteditable', 'Escape', '<div contenteditable="true"><b id="t"></b></div>', false],
        ['Escape in a read-only contenteditable', 'Escape', '<div contenteditable="false"><b id="t"></b></div>', true],
        ['Escape with a modal open', 'Escape', '<div class="ReactModal__Overlay"></div><b id="t"></b>', false],
        ['Escape with a popover open', 'Escape', '<div class="Popover"></div><b id="t"></b>', false],
    ])('for %s', (_name, key, html, expected) => {
        expect(shouldCloseOnEscape(pressKey(key, html, '#t'))).toBe(expected)
    })

    it('leaves an Escape that a handler in the page already took', () => {
        const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
        event.preventDefault()

        expect(shouldCloseOnEscape(event)).toBe(false)
    })
})
