import { shouldPlayGoldRings, watchForGoldRingsContent } from './holidayGoldRings'

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
        Object.defineProperty(content, 'innerText', { get: () => content.textContent ?? '' })
        content.textContent = 'Loading'
        const onMatch = jest.fn()
        const stopWatching = watchForGoldRingsContent(content, true, () => true, onMatch)

        content.textContent = '5 rows'
        await Promise.resolve()

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
        const stopWatching = watchForGoldRingsContent(content, true, () => isCurrentNavigation, onMatch)

        isCurrentNavigation = false
        content.textContent = 'Updated'
        await Promise.resolve()
        content.textContent = '5 rows'
        await Promise.resolve()

        expect(onMatch).not.toHaveBeenCalled()

        stopWatching()
    })
})
