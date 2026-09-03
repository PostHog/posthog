import { useLayoutEffect, useState } from 'react'

/**
 * Attaches stylesheets that the build keeps out of the boot CSS.
 *
 * `import href from './Feature.scss?url'` gives a component the URL of its own hashed CSS file
 * instead of bundling the file into `index.css`. The component then calls `loadStylesheet(href)`
 * from its lazy loader, or renders behind `useStylesheet(href)`, so the sheet is in
 * `document.styleSheets` before the first styled paint.
 */

const loadedHrefs = new Set<string>()
const pendingLoads = new Map<string, Promise<void>>()

export function loadStylesheet(href: string): Promise<void> {
    if (loadedHrefs.has(href)) {
        return Promise.resolve()
    }
    const pending = pendingLoads.get(href)
    if (pending) {
        return pending
    }
    const load = new Promise<void>((resolve) => {
        const link = document.createElement('link')
        link.rel = 'stylesheet'
        link.href = href
        link.onload = () => {
            loadedHrefs.add(href)
            pendingLoads.delete(href)
            resolve()
        }
        // An unstyled feature is better than one that never renders, so resolve on error too.
        // Leaving the href out of loadedHrefs means the next mount tries the fetch again.
        link.onerror = () => {
            console.error(`Failed to load stylesheet ${href}`)
            pendingLoads.delete(href)
            link.remove()
            resolve()
        }
        document.head.appendChild(link)
    })
    pendingLoads.set(href, load)
    return load
}

/**
 * True once `href` is attached, or at once when there is no stylesheet to attach.
 * Callers render a placeholder while this is false.
 */
export function useStylesheet(href: string | undefined): boolean {
    const [ready, setReady] = useState(() => !href || loadedHrefs.has(href))
    useLayoutEffect(() => {
        if (!href || loadedHrefs.has(href)) {
            setReady(true)
            return
        }
        let cancelled = false
        void loadStylesheet(href).then(() => {
            if (!cancelled) {
                setReady(true)
            }
        })
        return () => {
            cancelled = true
        }
    }, [href])
    return ready
}
