import {
    isGoldRingsMuted,
    listenForGoldRingsOptOut,
    shouldPlayGoldRings,
    watchForGoldRingsContent,
} from './holidayGoldRings'

describe('gold rings opt-out', () => {
    afterEach(() => {
        sessionStorage.removeItem('christmas-gold-rings-muted')
        jest.useRealTimers()
    })

    test.each(['I hate Xmas', 'ihatexmas', 'I  HATE   XMAS'])('accepts %s', (phrase) => {
        jest.useFakeTimers()
        const stopListening = listenForGoldRingsOptOut(() => true)

        for (const key of phrase) {
            window.dispatchEvent(new KeyboardEvent('keydown', { key }))
        }

        expect(isGoldRingsMuted()).toBe(true)
        stopListening()
    })

    test('resets an incomplete phrase after a pause', () => {
        jest.useFakeTimers()
        const stopListening = listenForGoldRingsOptOut(() => true)

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

    test('ignores password input', () => {
        jest.useFakeTimers()
        const input = document.createElement('input')
        input.type = 'password'
        document.body.appendChild(input)
        const stopListening = listenForGoldRingsOptOut(() => true)

        for (const key of 'IhateXmas') {
            input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key }))
        }

        expect(isGoldRingsMuted()).toBe(false)
        stopListening()
        input.remove()
    })
})

describe('shouldPlayGoldRings', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    test.each([
        ['December 24', new Date(2026, 11, 24), true, '5 rings', false],
        ['December 25', new Date(2026, 11, 25), true, '5 rings', true],
        ['December 31', new Date(2026, 11, 31), true, '5 rings', true],
        ['January 1', new Date(2027, 0, 1), true, '5 rings', true],
        ['January 5', new Date(2027, 0, 5), true, '5 rings', true],
        ['January 6', new Date(2027, 0, 6), true, '5 rings', false],
        ['flag off', new Date(2026, 11, 25), false, '5 rings', false],
        ['no standalone 5', new Date(2026, 11, 25), true, '15 rings', false],
        ['letters before and after 5', new Date(2026, 11, 25), true, 'abc5def', false],
        ['number with unit', new Date(2026, 11, 25), true, '5ms', false],
        ['decimal', new Date(2026, 11, 25), true, '0.5', false],
        ['thousands', new Date(2026, 11, 25), true, '5,000', false],
        ['no 5', new Date(2026, 11, 25), true, 'gold rings', false],
    ] as const)('%s', (_name, date, enabled, content, expected) => {
        expect(shouldPlayGoldRings(date, enabled, content)).toBe(expected)
    })

    test('checks content after it updates', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('div')
        const readInnerText = jest.fn(() => content.textContent ?? '')
        Object.defineProperty(content, 'innerText', { get: readInnerText })
        content.textContent = 'Loading'
        const onMatch = jest.fn()
        const stopWatching = watchForGoldRingsContent(
            () => content,
            () => true,
            () => true,
            () => false,
            onMatch
        )

        content.textContent = '5 rows'
        await Promise.resolve()
        jest.advanceTimersByTime(20)

        expect(onMatch).toHaveBeenCalledTimes(1)
        expect(readInnerText).toHaveBeenCalledTimes(1)

        stopWatching()
    })

    test('keeps table cell boundaries when rows arrive', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('table')
        const onMatch = jest.fn()
        const stopWatching = watchForGoldRingsContent(
            () => content,
            () => true,
            () => true,
            () => false,
            onMatch
        )
        const row = document.createElement('tr')
        for (const value of ['Example cohort', '5', 'Example user']) {
            const cell = document.createElement('td')
            cell.textContent = value
            row.appendChild(cell)
        }
        Object.defineProperty(row, 'innerText', { value: 'Example cohort\t5\tExample user' })
        expect(row.textContent).toBe('Example cohort5Example user')

        content.appendChild(row)
        await Promise.resolve()
        jest.advanceTimersByTime(20)

        expect(onMatch).toHaveBeenCalledTimes(1)
        stopWatching()
    })

    test('stops checking after navigation changes', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('div')
        Object.defineProperty(content, 'innerText', { get: () => content.textContent ?? '' })
        content.textContent = 'Loading'
        let isCurrentNavigation = true
        const onMatch = jest.fn()
        const stopWatching = watchForGoldRingsContent(
            () => content,
            () => true,
            () => isCurrentNavigation,
            () => false,
            onMatch
        )

        isCurrentNavigation = false
        content.textContent = 'Updated'
        await Promise.resolve()
        jest.advanceTimersByTime(20)
        content.textContent = '5 rows'
        await Promise.resolve()
        jest.advanceTimersByTime(20)

        expect(onMatch).not.toHaveBeenCalled()

        stopWatching()
    })

    test('waits for the scene container', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('div')
        content.textContent = '5 rows'
        const onMatch = jest.fn()
        let mounted = false
        const stopWatching = watchForGoldRingsContent(
            () => (mounted ? content : null),
            () => true,
            () => true,
            () => false,
            onMatch
        )

        mounted = true
        document.body.appendChild(content)
        await Promise.resolve()

        expect(onMatch).toHaveBeenCalledTimes(1)

        stopWatching()
        content.remove()
    })

    test('does not replay when the watcher resumes on the same navigation', () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('div')
        content.textContent = '5 rows'
        let played = false
        const onMatch = jest.fn(() => {
            played = true
        })
        const watch = (): (() => void) =>
            watchForGoldRingsContent(
                () => content,
                () => true,
                () => true,
                () => played,
                onMatch
            )

        watch()
        watch()

        expect(onMatch).toHaveBeenCalledTimes(1)
    })

    test('does not play after the flag turns off', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('div')
        content.textContent = 'Loading'
        let enabled = true
        const onMatch = jest.fn()
        const stopWatching = watchForGoldRingsContent(
            () => content,
            () => enabled,
            () => true,
            () => false,
            onMatch
        )

        enabled = false
        content.textContent = '5 rows'
        await Promise.resolve()
        jest.advanceTimersByTime(20)

        expect(onMatch).not.toHaveBeenCalled()
        stopWatching()
    })

    test('stops watching after the observation window', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(2026, 11, 25))

        const content = document.createElement('div')
        content.textContent = 'Loading'
        const onMatch = jest.fn()
        const stopWatching = watchForGoldRingsContent(
            () => content,
            () => true,
            () => true,
            () => false,
            onMatch
        )

        jest.advanceTimersByTime(10_001)
        content.textContent = '5 rows'
        await Promise.resolve()
        jest.advanceTimersByTime(20)

        expect(onMatch).not.toHaveBeenCalled()
        stopWatching()
    })
})
