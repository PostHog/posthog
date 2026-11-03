import { isGoldRingsMuted, listenForGoldRingsKeys } from './holidayGoldRings'

describe('holiday gold rings keys', () => {
    afterEach(() => {
        sessionStorage.removeItem('christmas-gold-rings-muted')
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each([
        ['flag on before December', new Date(2026, 9, 22), true, 1],
        ['flag on after Christmas', new Date(2027, 0, 6), true, 1],
        ['flag off during Christmas', new Date(2026, 11, 25), false, 0],
    ] as const)('%s', (_name, date, enabled, expected) => {
        jest.useFakeTimers()
        jest.setSystemTime(date)
        const play = jest.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
        jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation()
        const stopListening = listenForGoldRingsKeys(() => enabled)

        window.dispatchEvent(new KeyboardEvent('keydown', { key: '5' }))

        expect(play).toHaveBeenCalledTimes(expected)
        stopListening()
    })

    test('plays once for a held key', () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))
        const play = jest.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
        jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation()
        const stopListening = listenForGoldRingsKeys(() => true)

        window.dispatchEvent(new KeyboardEvent('keydown', { key: '5' }))
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '5', repeat: true }))

        expect(play).toHaveBeenCalledTimes(1)
        stopListening()
    })

    test.each(['I hate Xmas', 'ihatexmas', 'I  HATE   XMAS'])('turns off for %s', (phrase) => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))
        const play = jest.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
        jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation()
        const stopListening = listenForGoldRingsKeys(() => true)

        for (const key of phrase) {
            window.dispatchEvent(new KeyboardEvent('keydown', { key }))
        }
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '5' }))

        expect(isGoldRingsMuted()).toBe(true)
        expect(play).not.toHaveBeenCalled()
        stopListening()
    })

    test('resets an incomplete opt-out phrase after a pause', () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))
        const stopListening = listenForGoldRingsKeys(() => true)

        for (const key of 'I hate') {
            window.dispatchEvent(new KeyboardEvent('keydown', { key }))
        }
        jest.advanceTimersByTime(2_001)
        for (const key of ' Xmas') {
            window.dispatchEvent(new KeyboardEvent('keydown', { key }))
        }

        expect(isGoldRingsMuted()).toBe(false)
        stopListening()
    })

    test.each([
        ['an input', '<input data-key-target />'],
        ['a textarea', '<textarea data-key-target></textarea>'],
        ['contenteditable text', '<div contenteditable="true"><span data-key-target></span></div>'],
        ['a code editor', '<div class="monaco-editor"><span data-key-target></span></div>'],
    ])('plays without swallowing 5 while typing in %s', (_name, markup) => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))
        const play = jest.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
        const container = document.createElement('div')
        container.innerHTML = markup
        document.body.appendChild(container)
        const stopListening = listenForGoldRingsKeys(() => true)

        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: '5' })
        container.querySelector('[data-key-target]')?.dispatchEvent(event)

        expect(play).toHaveBeenCalledTimes(1)
        expect(event.defaultPrevented).toBe(false)
        stopListening()
        container.remove()
    })

    test('does not play or track the opt-out phrase in password inputs', () => {
        jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation()
        const play = jest.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
        const input = document.createElement('input')
        input.type = 'password'
        document.body.appendChild(input)
        const stopListening = listenForGoldRingsKeys(() => true)

        for (const key of 'I hate Xmas') {
            input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key }))
        }
        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: '5' })
        input.dispatchEvent(event)

        expect(play).not.toHaveBeenCalled()
        expect(isGoldRingsMuted()).toBe(false)
        expect(event.defaultPrevented).toBe(false)
        stopListening()
        input.remove()
    })

    test('can opt out while typing in an input', () => {
        jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation()
        const input = document.createElement('input')
        document.body.appendChild(input)
        const stopListening = listenForGoldRingsKeys(() => true)

        for (const key of 'I hate Xmas') {
            input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key }))
        }

        expect(isGoldRingsMuted()).toBe(true)
        stopListening()
        input.remove()
    })
})
