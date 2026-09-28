import type { PreflightStatus } from '~/types'

/**
 * Present while the app runs inside another shell through `mountLegacyApp` (frontend/src/embed).
 * Kept in a leaf module so app code can ask "am I embedded?" without importing the embed entry.
 */
export interface EmbedContext {
    /** The element the app renders into. It carries the `theme` attribute that `body` carries otherwise. */
    root: HTMLElement
    /** Served in place of `/_preflight/`, which only answers same-origin requests. */
    preflight: PreflightStatus
    signOut: () => void
}

let embedContext: EmbedContext | null = null

export function setEmbedContext(context: EmbedContext | null): void {
    embedContext = context
}

export function getEmbedContext(): EmbedContext | null {
    return embedContext
}
