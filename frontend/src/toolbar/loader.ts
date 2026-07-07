import type { PostHog } from 'posthog-js'

import type { ToolbarParams } from '~/types'

// The toolbar loader: a tiny classic script served as /static/toolbar.js. posthog-js (every
// version, forever) injects it with a plain <script> tag and calls window.ph_load_toolbar on
// the script's load event — that contract must never change. This file defines those globals
// synchronously, then dynamic-import()s the real toolbar app (an ESM entry with code-split
// chunks under ./toolbar/) the first time the toolbar actually loads.
//
// Rules for this file:
// - No value imports (type imports are fine — they're erased). Anything bundled here ships on
//   every toolbar load before a single feature runs; app code belongs in the ESM entry.
//   check-toolbar-size.mjs caps this file's size to keep that honest.
// - No eval / new Function — customer pages run strict CSPs; check-toolbar-csp-eval.mjs
//   asserts zero violations for this file.
// - Resolve chunks relative to the script's own URL, never an absolute host: the same
//   artifacts are served from Django /static/ on any region or self-hosted instance, and from
//   the versioned, major-alias and compatibility prefixes on the posthog-js CDN.

type ToolbarModule = typeof import('~/toolbar/index')

// document.currentScript is only set during the initial synchronous evaluation, so capture it
// at module scope. It is null when the loader is evaluated as a module (tests) — then the
// build-time public path (set for posthog-js versioned CDN bundles) is the fallback.
const scriptSrc = (document.currentScript as HTMLScriptElement | null)?.src

function resolveAppUrl(fileName: string): string {
    const base = scriptSrc || __POSTHOG_TOOLBAR_PUBLIC_PATH__
    if (!base) {
        throw new Error('PostHog toolbar loader could not determine its own URL')
    }
    return new URL(`toolbar/${fileName}`, base).href
}

async function importWithRetry(url: string, retries: number, delayMs: number): Promise<ToolbarModule> {
    try {
        return await import(url)
    } catch (error) {
        if (retries <= 0) {
            throw error
        }
        await new Promise((resolve) => setTimeout(resolve, delayMs))
        return importWithRetry(url, retries - 1, delayMs * 2)
    }
}

let appPromise: Promise<ToolbarModule> | null = null

function loadApp(): Promise<ToolbarModule> {
    if (!appPromise) {
        appPromise = importWithRetry(resolveAppUrl(__POSTHOG_TOOLBAR_APP_ENTRY__), 2, 300)
            .catch(() => {
                // Version-skew fallback: a cached loader can reference a hashed entry that no
                // longer exists on the origin after a deploy. The hashless copy always points at
                // the latest build, whose chunk references are self-consistent. Same 5-minute
                // cache bucket as the toolbar.css loader.
                const fiveMinutesInMillis = 5 * 60 * 1000
                const cacheBuster = Math.floor(Date.now() / fiveMinutesInMillis) * fiveMinutesInMillis
                return import(resolveAppUrl(`toolbar-app.js?t=${cacheBuster}`))
            })
            .then((module) => {
                controllerDelegate = module.posthogToolbarController
                return module
            })
            .catch((error) => {
                appPromise = null // a later ph_load_toolbar call gets a fresh attempt
                throw error
            })
    }
    return appPromise
}

// The app module exposes the real window.posthogToolbarController when it evaluates, but
// third-party code may grab the global right after the loader script loads — give those early
// consumers a stub that starts forwarding once the app is in.
let controllerDelegate: ToolbarModule['posthogToolbarController'] | null = null
const controllerStub = {
    get isLoaded(): boolean {
        return controllerDelegate ? controllerDelegate.isLoaded : false
    },
    get isVisible(): boolean {
        return controllerDelegate ? controllerDelegate.isVisible : false
    },
    get isAuthenticated(): boolean {
        return controllerDelegate ? controllerDelegate.isAuthenticated : false
    },
    show(): void {
        controllerDelegate?.show()
    },
    hide(): void {
        controllerDelegate?.hide()
    },
    authenticate(): void {
        controllerDelegate?.authenticate()
    },
    destroy(): void {
        controllerDelegate?.destroy()
    },
}

const win = window as any

win['posthogToolbarController'] = win['posthogToolbarController'] || controllerStub

win['ph_load_toolbar'] = async function (toolbarParams: ToolbarParams, posthog?: PostHog): Promise<void> {
    // Start the load-duration clock before the app module and its chunks are fetched — the
    // fetch is part of what the user waits for. loadToolbar keeps the earliest timestamp.
    win.__posthog_toolbar_load_start = performance.now()
    let module: ToolbarModule
    try {
        module = await loadApp()
    } catch (error) {
        // Graceful degradation is "no toolbar", never a broken host page.
        console.warn('[PostHog Toolbar] Failed to load the toolbar bundle', error)
        return
    }
    await module.loadToolbar(toolbarParams, posthog)
}

/** @deprecated, use "ph_load_toolbar" instead */
win['ph_load_editor'] = win['ph_load_toolbar']
