import { resetContext } from 'kea'
import type { Root } from 'react-dom/client'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { TOOLBAR_ID } from '~/toolbar/utils'

// Private module-level state — persists across the singleton within the IIFE bundle
let _reactRoot: Root | null = null
let _container: HTMLElement | null = null
let _loaded: boolean = false

/** Called from index.tsx after createRoot() and root.render() to capture refs for destroy(). */
export function setToolbarRefs(root: Root, container: HTMLElement): void {
    _reactRoot = root
    _container = container
    _loaded = true
}

/** Reset all refs to null — used internally by destroy(). */
export function clearToolbarRefs(): void {
    _reactRoot = null
    _container = null
    _loaded = false
}

/**
 * Public API for third-party code to programmatically control the toolbar.
 * Exposed on the host page as `window.posthogToolbarController`.
 */
export class PostHogToolbarController {
    /** Whether the toolbar React root is mounted. */
    get isLoaded(): boolean {
        return _loaded
    }

    /** Whether the toolbar button is currently visible. Returns false if toolbar is not loaded. */
    get isVisible(): boolean {
        if (!_loaded) {
            return false
        }
        return toolbarConfigLogic.findMounted()?.values.buttonVisible ?? false
    }

    /** Whether the toolbar has a valid authentication session. Returns false if toolbar is not loaded. */
    get isAuthenticated(): boolean {
        if (!_loaded) {
            return false
        }
        return toolbarConfigLogic.findMounted()?.values.isAuthenticated ?? false
    }

    /** Make the toolbar button visible. No-op if toolbar is not loaded. */
    show(): void {
        toolbarConfigLogic.findMounted()?.actions.showButton()
    }

    /** Hide the toolbar button. No-op if toolbar is not loaded. */
    hide(): void {
        toolbarConfigLogic.findMounted()?.actions.hideButton()
    }

    /** Trigger the OAuth PKCE authentication flow. No-op if already authenticated or toolbar is not loaded. */
    authenticate(): void {
        if (this.isAuthenticated) {
            return
        }
        toolbarConfigLogic.findMounted()?.actions.authenticate()
    }

    /** Unmount the toolbar React tree, remove DOM elements, and reset Kea context. Idempotent. */
    destroy(): void {
        if (!_loaded) {
            return
        }

        // Capture refs before clearing — clearToolbarRefs() nulls them, but we
        // clear first so that isLoaded becomes false immediately, preventing
        // external callers from interacting with a half-torn-down toolbar.
        const reactRoot = _reactRoot
        const container = _container
        clearToolbarRefs()

        reactRoot?.unmount()
        container?.parentNode?.removeChild(container)

        // Remove the shadow DOM host element if it still exists
        document.getElementById(TOOLBAR_ID)?.remove()

        resetContext({})
    }
}

export const posthogToolbarController = new PostHogToolbarController()
