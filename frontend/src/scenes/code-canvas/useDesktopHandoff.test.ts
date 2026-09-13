import { act, renderHook } from '@testing-library/react'

import { HANDOFF_GRACE_MS, useDesktopHandoff } from './useDesktopHandoff'

describe('useDesktopHandoff', () => {
    let location: { href: string }

    beforeEach(() => {
        jest.useFakeTimers()
        location = { href: 'https://app.posthog.com/code/task/task-1' }
        Object.defineProperty(window, 'location', { value: location, writable: true })
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    it('offers a way out when the app never takes over', () => {
        const { result } = renderHook(() => useDesktopHandoff('posthog-code://task/task-1'))

        expect(location.href).toBe('posthog-code://task/task-1')
        expect(result.current.status).toBe('opening')

        act(() => jest.advanceTimersByTime(HANDOFF_GRACE_MS))
        expect(result.current.status).toBe('stalled')
    })

    it('fires the link again on retry, and shows that it is trying', () => {
        const { result } = renderHook(() => useDesktopHandoff('posthog-code://task/task-1'))
        act(() => jest.advanceTimersByTime(HANDOFF_GRACE_MS))

        location.href = 'https://app.posthog.com/code/task/task-1'
        act(() => result.current.retry?.())

        expect(location.href).toBe('posthog-code://task/task-1')
        expect(result.current.status).toBe('opening')
    })

    it('fires nothing while the target is unknown', () => {
        const { result } = renderHook(() => useDesktopHandoff(null))

        act(() => jest.advanceTimersByTime(HANDOFF_GRACE_MS))
        expect(location.href).toBe('https://app.posthog.com/code/task/task-1')
        expect(result.current.status).toBe('opening')
        expect(result.current.retry).toBeUndefined()
    })
})
