jest.unmock('lib/utils/lazyStylesheet')

import { act, renderHook } from '@testing-library/react'

import { loadStylesheet, useStylesheet } from './lazyStylesheet'

describe('lazyStylesheet', () => {
    let hrefCounter = 0
    const uniqueHref = (): string => `/static/stylesheets/test-${hrefCounter++}.css`

    const linksFor = (href: string): HTMLLinkElement[] =>
        Array.from(document.head.querySelectorAll<HTMLLinkElement>(`link[rel="stylesheet"][href="${href}"]`))

    const flushPromises = (): Promise<void> => act(async () => {})

    it.each(['load', 'error'])('resolves when the link fires %s', async (eventType) => {
        const href = uniqueHref()
        const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})

        const promise = loadStylesheet(href)
        const [link] = linksFor(href)
        link.dispatchEvent(new Event(eventType))

        await expect(promise).resolves.toBeUndefined()
        consoleError.mockRestore()
    })

    it('appends one link for a href however many callers ask for it', async () => {
        const href = uniqueHref()

        const first = loadStylesheet(href)
        const second = loadStylesheet(href)
        expect(linksFor(href)).toHaveLength(1)

        linksFor(href)[0].dispatchEvent(new Event('load'))
        await Promise.all([first, second])

        await loadStylesheet(href)
        expect(linksFor(href)).toHaveLength(1)
    })

    it('useStylesheet gates until the sheet loads, then answers synchronously', async () => {
        const href = uniqueHref()

        const { result } = renderHook(() => useStylesheet(href))
        expect(result.current).toBe(false)
        expect(linksFor(href)).toHaveLength(1)

        act(() => {
            linksFor(href)[0].dispatchEvent(new Event('load'))
        })
        await flushPromises()
        expect(result.current).toBe(true)

        const { result: second } = renderHook(() => useStylesheet(href))
        expect(second.current).toBe(true)
    })
})
