import { keepTabFocusWithin } from './keepTabFocusWithin'

describe('keepTabFocusWithin', () => {
    let container: HTMLDivElement

    beforeEach(() => {
        container = document.createElement('div')
        container.innerHTML = `
            <div contenteditable="true" tabindex="0" data-attr="editor"></div>
            <input type="hidden" />
            <button disabled>Disabled</button>
            <button data-attr="middle">Middle</button>
            <button data-attr="send">Send</button>
        `
        document.body.appendChild(container)
    })

    afterEach(() => {
        container.remove()
    })

    const pressTab = (shiftKey: boolean): jest.Mock => {
        const preventDefault = jest.fn()
        keepTabFocusWithin(container, { shiftKey, preventDefault })
        return preventDefault
    }

    const focus = (attr: string): void => {
        container.querySelector<HTMLElement>(`[data-attr="${attr}"]`)!.focus()
    }

    test.each([
        { from: 'send', shiftKey: false, to: 'editor' },
        { from: 'editor', shiftKey: true, to: 'send' },
    ])('wraps $from to $to when shift is $shiftKey', ({ from, shiftKey, to }) => {
        focus(from)

        expect(pressTab(shiftKey)).toHaveBeenCalled()
        expect(document.activeElement?.getAttribute('data-attr')).toBe(to)
    })

    it('leaves Tab alone between the first and last elements', () => {
        focus('middle')

        expect(pressTab(false)).not.toHaveBeenCalled()
        expect(document.activeElement?.getAttribute('data-attr')).toBe('middle')
    })
})
