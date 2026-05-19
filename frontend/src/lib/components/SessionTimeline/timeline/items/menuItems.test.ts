import { buildOpenInActivityTabMenuItem } from './menuItems'

describe('buildOpenInActivityTabMenuItem', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            current_team: { id: 1 },
        } as any
    })

    afterEach(() => {
        delete window.POSTHOG_APP_CONTEXT
    })

    it('returns no menu items when event context is missing', () => {
        expect(buildOpenInActivityTabMenuItem({ timestamp: '2024-07-09T12:00:02.500Z' })).toEqual([])
        expect(buildOpenInActivityTabMenuItem({ eventId: '018dc30d-a8a5-7257-9faf-dcd97c0e19cf' })).toEqual([])
    })

    it('opens the project event route so activity view can focus that event', () => {
        const openSpy = jest.spyOn(window, 'open').mockImplementation(() => null)
        const eventId = '018dc30d-a8a5-7257-9faf-dcd97c0e19cf'
        const timestamp = '2024-07-09T12:00:02.500Z'

        const items = buildOpenInActivityTabMenuItem({ eventId, timestamp })

        expect(items).toHaveLength(1)
        expect(items[0].label).toBe('Open in activity tab')

        items[0].onClick()

        expect(openSpy).toHaveBeenCalledTimes(1)
        const [openedUrl, target, features] = openSpy.mock.calls[0]

        expect(target).toBe('_blank')
        expect(features).toBe('noopener,noreferrer')

        const parsed = new URL(String(openedUrl), 'http://localhost')
        expect(parsed.pathname).toContain(`/events/${eventId}/`)
        expect(decodeURIComponent(parsed.pathname.split('/').at(-1) ?? '')).toBe(timestamp)
        expect(parsed.search).toBe('')
        expect(parsed.hash).toBe('')

        openSpy.mockRestore()
    })
})
