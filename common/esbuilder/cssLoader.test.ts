import { CSS_ATTEMPT_TIMEOUT_MS, cssLoaderScript, stableCssLoaderScript } from './cssLoader.mjs'

const CSS_FILE = 'index-ABCD1234.css'
const CSS_FALLBACK = 'index.css?t=99'
const STATIC = 'https://cdn.example.com/static/'

type FakeLink = {
    rel?: string
    crossOrigin?: string
    href?: string
    sheet?: object | null
    addEventListener: (type: string, listener: () => void) => void
    dispatch: (type: string) => void
}

function makeLink(): FakeLink {
    const listeners: Record<string, (() => void)[]> = {}
    return {
        sheet: null,
        addEventListener: (type: string, listener: () => void) => {
            ;(listeners[type] ??= []).push(listener)
        },
        dispatch: (type: string) => listeners[type]?.forEach((listener) => listener()),
    }
}

function runLoader({
    cssFileFallback = CSS_FALLBACK,
    apiKey = 'phc_test' as string | null,
    script = cssLoaderScript(CSS_FILE, cssFileFallback),
} = {}): {
    ready: Promise<boolean>
    links: FakeLink[]
    beacons: Record<string, any>[]
    win: Record<string, any>
} {
    const links: FakeLink[] = []
    const beacons: Record<string, any>[] = []
    const win: Record<string, any> = {
        JS_URL: 'https://cdn.example.com',
        JS_POSTHOG_API_KEY: apiKey,
        JS_POSTHOG_HOST: 'https://capture.example.com',
        // A share path, because this loader also runs on exporter.html.
        location: { origin: 'https://app.example.com', href: 'https://app.example.com/shared/sh4r3-t0k3n' },
        localStorage: { getItem: () => null },
    }
    const doc = {
        createElement: (): FakeLink => makeLink(),
        head: {
            appendChild: (link: FakeLink) => links.push(link),
            insertBefore: (link: FakeLink, before: FakeLink) => links.splice(links.indexOf(before), 0, link),
        },
    }
    const nav = {
        sendBeacon: (_url: string, body: string) => {
            beacons.push(JSON.parse(body))
            return true
        },
    }
    // The inline loader runs in the page as a classic script: these are all globals there.
    new Function('window', 'document', 'navigator', 'console', 'fetch', script)(
        win,
        doc,
        nav,
        { error: () => {} },
        () => Promise.resolve()
    )
    return { ready: win.ESBUILD_CSS_READY, links, beacons, win }
}

/** A stylesheet that really applied has a `sheet`; a response that is not CSS fires `load` without one. */
function applyStylesheet(link: FakeLink): void {
    link.sheet = {}
    link.dispatch('load')
}

describe('css loader script', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('attaches the hashed stylesheet for CORS and reports ready once it applies', async () => {
        const { ready, links, beacons } = runLoader()
        expect(links).toHaveLength(1)
        expect(links[0]).toMatchObject({ rel: 'stylesheet', crossOrigin: 'anonymous', href: `${STATIC}${CSS_FILE}` })

        applyStylesheet(links[0])

        await expect(ready).resolves.toBe(true)
        expect(beacons).toHaveLength(0)
    })

    it.each([
        ['fails', 'failed to load', (link: FakeLink) => link.dispatch('error')],
        ['stalls', 'stalled', () => jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)],
        ['serves a response that is not CSS', 'loaded but did not apply', (link: FakeLink) => link.dispatch('load')],
    ])('loads the hashless copy and reports when the hashed stylesheet %s', (_case, reason, fail) => {
        const { links, beacons } = runLoader()
        fail(links[0])

        expect(links).toHaveLength(2)
        expect(links[1].href).toBe(`${STATIC}${CSS_FALLBACK}`)
        expect(beacons).toHaveLength(1)
        expect(beacons[0].properties.$exception_list[0]).toMatchObject({
            type: 'StylesheetLoadError',
            value: `App stylesheet ${reason}`,
        })
        expect(beacons[0].properties).toMatchObject({
            stylesheet_href: `${STATIC}${CSS_FILE}`,
            stylesheet_attempt: 1,
            $exception_level: 'error',
            $process_person_profile: false,
        })
        // The path can carry a share token, so the beacon must keep the origin only.
        expect(JSON.stringify(beacons[0])).not.toContain('sh4r3-t0k3n')
    })

    it('retries with a fresh query, then reports the page unstyled once every attempt fails', async () => {
        const { ready, links, beacons } = runLoader()
        for (let attempt = 0; attempt < 3; attempt++) {
            jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        }

        // The last attempt asks for the same file with a query no cache entry and no hung
        // connection has seen.
        expect(links).toHaveLength(3)
        expect(links[2].href).toMatch(new RegExp(`^${STATIC}index\\.css\\?t=99&retry=\\d+$`))

        await expect(ready).resolves.toBe(false)
        expect(beacons).toHaveLength(3)
        expect(beacons[2].properties.$exception_level).toBe('fatal')
    })

    it('reports ready when a stylesheet abandoned by a timeout lands late', async () => {
        const { ready, links } = runLoader()
        jest.advanceTimersByTime(CSS_ATTEMPT_TIMEOUT_MS)
        expect(links).toHaveLength(2)

        applyStylesheet(links[0])

        await expect(ready).resolves.toBe(true)
    })

    it('recovers without a beacon when capture is opted out', () => {
        const { links, beacons } = runLoader({ apiKey: null })
        links[0].dispatch('error')

        expect(links).toHaveLength(2)
        expect(beacons).toHaveLength(0)
    })

    it('still has a retry to fall back on in a dev build with no hashless copy', () => {
        const { links } = runLoader({ cssFileFallback: CSS_FILE })
        links[0].dispatch('error')

        expect(links).toHaveLength(2)
        expect(links[1].href).toMatch(new RegExp(`^${STATIC}index-ABCD1234\\.css\\?retry=\\d+$`))
        links[1].dispatch('error')
        expect(links).toHaveLength(2)
    })

    // The stable build splits the stylesheet; a split stylesheet that fails must not leave the page
    // unstyled, because the full stylesheet holds every rule.
    it.each([
        ['every split stylesheet applies', false],
        ['a split stylesheet fails', true],
    ])('reports ready when %s', async (_name, splitFails) => {
        const { ready, links } = runLoader({
            script: stableCssLoaderScript(['a-1.css', 'b-2.css'], CSS_FILE, CSS_FALLBACK),
        })
        expect(links.map((link) => link.href)).toEqual([`${STATIC}a-1.css`, `${STATIC}b-2.css`])

        applyStylesheet(links[0])
        if (splitFails) {
            links[1].dispatch('error')
            await Promise.resolve()
            expect(links[2].href).toBe(`${STATIC}${CSS_FILE}`)
            applyStylesheet(links[2])
        } else {
            applyStylesheet(links[1])
        }

        await expect(ready).resolves.toBe(true)
        expect(links).toHaveLength(splitFails ? 3 : 2)
    })

    describe('stable loader for lazy stylesheets', () => {
        const stable = (): ReturnType<typeof runLoader> =>
            runLoader({ script: stableCssLoaderScript(['eager-1.css'], CSS_FILE, CSS_FALLBACK) })
        const lazyLoad = (win: any, entries: [string, number][] | null): Promise<boolean> =>
            (win as any).ESBUILD_LOAD_CSS(entries)

        // Scenes load in any order, but the cascade among their stylesheets must match the full one.
        it('inserts lazy stylesheets in rank order whatever order they load in', () => {
            const { links, win } = stable()
            void lazyLoad(win, [[`${STATIC}later.css`, 20]])
            void lazyLoad(win, [[`${STATIC}earlier.css`, 10]])

            expect(links.map((link) => link.href)).toEqual([
                `${STATIC}eager-1.css`,
                `${STATIC}earlier.css`,
                `${STATIC}later.css`,
            ])
        })

        it('loads the full stylesheet when the chunk cannot resolve its groups, and nothing after it', async () => {
            const { links, win } = stable()
            const loaded = lazyLoad(win, null)

            expect(links[links.length - 1].href).toBe(`${STATIC}${CSS_FILE}`)
            applyStylesheet(links[links.length - 1])
            await expect(loaded).resolves.toBe(true)

            // A split stylesheet after the full one would override its later rules.
            const linksBefore = links.length
            await expect(lazyLoad(win, [[`${STATIC}later.css`, 99]])).resolves.toBe(true)
            expect(links).toHaveLength(linksBefore)
        })

        // A chunk whose styles never load throws so the chunk-load recovery runs; a retry must fetch again.
        it('resolves false when every fallback fails, and fetches again on the next attempt', async () => {
            const { links, win } = stable()
            const failed = lazyLoad(win, [[`${STATIC}scene.css`, 5]])
            links[1].dispatch('error')
            await Promise.resolve()
            for (let attempt = 2; attempt < links.length || attempt < 5; attempt++) {
                links[attempt]?.dispatch('error')
                await Promise.resolve()
            }
            await expect(failed).resolves.toBe(false)

            const linksBefore = links.length
            void lazyLoad(win, [[`${STATIC}scene.css`, 5]])
            expect(links.length).toBeGreaterThan(linksBefore)
        })

        // A second group requested while the full stylesheet is still loading must not insert its own
        // link, because that link would land after the full one already in <head> and could override it.
        it('does not insert a new link while the full-stylesheet fallback is in flight, and resolves once it applies', async () => {
            const { links, win } = stable()
            const firstRequest = lazyLoad(win, [[`${STATIC}scene.css`, 5]])
            links[1].dispatch('error')
            await Promise.resolve()
            const fullLink = links[links.length - 1]
            expect(fullLink.href).toBe(`${STATIC}${CSS_FILE}`)

            const linksBefore = links.length
            const secondRequest = lazyLoad(win, [[`${STATIC}other.css`, 99]])
            expect(links).toHaveLength(linksBefore)

            applyStylesheet(fullLink)
            await expect(firstRequest).resolves.toBe(true)
            await expect(secondRequest).resolves.toBe(true)
            expect(links).toHaveLength(linksBefore)
        })

        // Once every fallback fails, a request that was waiting on it must still get its own stylesheet.
        it('inserts its own stylesheet once every full-stylesheet fallback fails, and resolves to that result', async () => {
            const { links, win } = stable()
            const firstRequest = lazyLoad(win, [[`${STATIC}scene.css`, 5]])
            links[1].dispatch('error')
            await Promise.resolve()

            const linksBefore = links.length
            const secondRequest = lazyLoad(win, [[`${STATIC}other.css`, 99]])
            // The full stylesheet's own retry ladder still runs, but no link for "other.css" yet.
            expect(links.some((link) => link.href === `${STATIC}other.css`)).toBe(false)

            for (let attempt = 2; attempt < links.length || attempt < 5; attempt++) {
                links[attempt]?.dispatch('error')
                await Promise.resolve()
            }
            await expect(firstRequest).resolves.toBe(false)
            await Promise.resolve()
            await Promise.resolve()

            expect(links.length).toBeGreaterThan(linksBefore)
            const otherLink = links[links.length - 1]
            expect(otherLink.href).toBe(`${STATIC}other.css`)

            applyStylesheet(otherLink)
            await expect(secondRequest).resolves.toBe(true)
        })
    })
})
