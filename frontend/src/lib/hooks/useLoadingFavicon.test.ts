import { renderHook } from '@testing-library/react'

import { useLoadingFavicon } from './useLoadingFavicon'

describe('useLoadingFavicon', () => {
    let favicon: HTMLLinkElement
    let shortcutIcon: HTMLLinkElement

    beforeEach(() => {
        favicon = document.createElement('link')
        favicon.rel = 'icon'
        favicon.href = '/static/icons/favicon-32x32.png'
        favicon.type = 'image/png'
        document.head.append(favicon)

        shortcutIcon = document.createElement('link')
        shortcutIcon.rel = 'shortcut icon'
        shortcutIcon.href = '/static/icons/favicon.ico'
        document.head.append(shortcutIcon)
    })

    afterEach(() => {
        favicon.remove()
        shortcutIcon.remove()
    })

    it('shows a loading favicon only while loading', () => {
        const { rerender, unmount } = renderHook(({ isLoading }) => useLoadingFavicon(isLoading), {
            initialProps: { isLoading: false },
        })

        expect(favicon.getAttribute('href')).toBe('/static/icons/favicon-32x32.png')
        expect(shortcutIcon.getAttribute('href')).toBe('/static/icons/favicon.ico')

        rerender({ isLoading: true })

        expect(favicon.getAttribute('href')).toBe('/static/icons/favicon-loading.svg')
        expect(favicon.type).toBe('image/svg+xml')
        expect(shortcutIcon.getAttribute('href')).toBe('/static/icons/favicon-loading.svg')

        rerender({ isLoading: false })

        expect(favicon.getAttribute('href')).toBe('/static/icons/favicon-32x32.png')
        expect(favicon.type).toBe('image/png')
        expect(shortcutIcon.getAttribute('href')).toBe('/static/icons/favicon.ico')
        expect(shortcutIcon.hasAttribute('type')).toBe(false)

        unmount()
    })

    it('restores the original favicon when unmounted', () => {
        const { unmount } = renderHook(() => useLoadingFavicon(true))

        unmount()

        expect(favicon.getAttribute('href')).toBe('/static/icons/favicon-32x32.png')
        expect(favicon.type).toBe('image/png')
        expect(shortcutIcon.getAttribute('href')).toBe('/static/icons/favicon.ico')
        expect(shortcutIcon.hasAttribute('type')).toBe(false)
    })
})
