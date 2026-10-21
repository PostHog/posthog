import type { ActionStepType } from '~/types'

import type { PageInspectCommand, PageSessionCommand } from './extensionPageToolbarLogic'

/**
 * The content script runs the toolbar's own logics in the page, signed in with the extension's OAuth tokens. The panel
 * shows their controls. A port carries commands to the page and state back to the panel.
 */

// pinned: extension port name, the panel and an already injected content script must agree on it
export const PAGE_TOOLBAR_PORT = 'posthog-toolbar-page'

export type PageToolbarMode = 'none' | 'inspect'

export interface PageToolbarTokens {
    accessToken: string
    refreshToken: string | null
    clientId: string
}

export interface PageToolbarSession extends PageToolbarTokens {
    uiHost: string
    dataAttributes: string[]
}

/** Each tool keeps its command types next to the logic that runs them in the page. */
export interface PageToolCommands {
    session: PageSessionCommand
    inspect: PageInspectCommand
}

export type PageToolName = keyof PageToolCommands

export type PageToolbarCommand = {
    [Tool in PageToolName]: { tool: Tool; command: PageToolCommands[Tool] }
}[PageToolName]

/** The panel sends `start` once per connection, then commands. */
export type PageToolbarRequest = { type: 'start'; session: PageToolbarSession; href: string } | PageToolbarCommand

export interface InspectedElementInfo {
    tagName: string
    actionStep: ActionStepType | null
    actions: { id: number; name: string | null }[]
}

export interface PageToolbarInspectState {
    /** The hovered or selected element in inspect mode. */
    element: InspectedElementInfo | null
    isSelected: boolean
}

export interface PageToolbarState {
    mode: PageToolbarMode
    inspect: PageToolbarInspectState
}

export type PageToolbarMessage =
    | { type: 'state'; state: PageToolbarState }
    /** The slices that changed since the last message. The rest keep their earlier value. */
    | { type: 'patch'; patch: Partial<PageToolbarState> }
    /** The page refreshed the tokens, which rotates the refresh token. */
    | { type: 'tokens'; tokens: PageToolbarTokens }
    | { type: 'token-expired' }

function isObject(message: unknown): message is Record<string, unknown> {
    return !!message && typeof message === 'object'
}

export function isPageToolbarRequest(message: unknown): message is PageToolbarRequest {
    return (
        isObject(message) &&
        (message.type === 'start' || (typeof message.tool === 'string' && isObject(message.command)))
    )
}

export function isPageToolbarMessage(message: unknown): message is PageToolbarMessage {
    return isObject(message) && typeof message.type === 'string'
}
