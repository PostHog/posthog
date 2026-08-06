import { SETUP_COMMAND_CARD_ID, focusSetupCommand } from './setupCommandFocus'

describe('focusSetupCommand', () => {
    afterEach(() => {
        document.body.innerHTML = ''
    })

    it('scrolls the setup command into view and flashes it', () => {
        const el = document.createElement('div')
        el.id = SETUP_COMMAND_CARD_ID
        const scrollIntoView = jest.fn()
        const animate = jest.fn()
        el.scrollIntoView = scrollIntoView
        el.animate = animate as unknown as Element['animate']
        document.body.appendChild(el)

        focusSetupCommand()

        expect(scrollIntoView).toHaveBeenCalledTimes(1)
        expect(animate).toHaveBeenCalledTimes(1)
    })

    it('is a no-op when the setup command card is not on the page', () => {
        expect(() => focusSetupCommand()).not.toThrow()
    })
})
