import type {
    CommonFilters,
    HeatmapFilters,
    HeatmapFixedPositionMode,
    ScrollDepthPosthogJsError,
} from 'lib/components/heatmaps/types'

import type { ActionStepType } from '~/types'

import type { PageHeatmapCommand } from './extensionPageHeatmapLogic'
import type { PageInspectCommand, PageSessionCommand } from './extensionPageToolbarLogic'

/**
 * The content script runs the toolbar's own logics in the page, signed in with the extension's OAuth tokens. The panel
 * shows their controls. A port carries commands to the page and state back to the panel.
 */

// pinned: extension port name, the panel and an already injected content script must agree on it
export const PAGE_TOOLBAR_PORT = 'posthog-toolbar-page'

export type PageToolbarMode = 'none' | 'heatmap' | 'inspect'

/** What the content script reads from the page's posthog-js through the page agent. */
export interface PageAnalyticsInfo {
    version: string | null
    scrollPropertiesDisabled: boolean
    /** The page's `scroll_root_selector`, which posthog-js measures scroll depth on instead of the window. */
    scrollRootSelector: string | string[] | null
    /** Null when the posthog-js version has no heatmaps module. */
    heatmapsEnabled: boolean | null
}

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
    heatmap: PageHeatmapCommand
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
    /** Null when the clickmap has no clicks for the element. */
    stats: {
        count: number
        clickCount: number
        rageclickCount: number
        deadclickCount: number
        rank: number
    } | null
    actions: { id: number; name: string | null }[]
}

export interface PageToolbarInspectState {
    /** The hovered or selected element in inspect mode, or an element picked from the clickmap list. */
    element: InspectedElementInfo | null
    isSelected: boolean
}

export interface PageToolbarHeatmapState {
    wildcardHref: string
    autoWildcardEnabled: boolean
    wildcardHrefTooSpecific: boolean
    wildcardHrefEndsWithSlash: boolean
    commonFilters: CommonFilters
    heatmapFilters: HeatmapFilters
    heatmapColorPalette: string | null
    heatmapFixedPositionMode: HeatmapFixedPositionMode
    viewportRange: { min: number; max: number }
    rawHeatmapLoading: boolean
    /** Whether the page's posthog-js collects heatmap data. `unknown` when the page has no `window.posthog`. */
    heatmapsCollection: 'enabled' | 'disabled' | 'unsupported' | 'unknown'
    scrollDepthPosthogJsError: ScrollDepthPosthogJsError
    clickmapsEnabled: boolean
    clickmapLoading: boolean
    processingProgress: { processed: number; total: number } | null
    matchLinksByHref: boolean
    countedElements: { text: string; tagName: string; count: number }[]
    clickCount: number
    canLoadMoreElementStats: boolean
    loadedElementStatsCount: number
    loadingAllElementStats: boolean
    areaSelectionActive: boolean
    areaFilter: { selector: string | null; tagName: string } | null
    savingHeatmap: boolean
    saveProgress: { done: number; total: number } | null
    saveResult: HeatmapSaveResult | null
}

export type HeatmapSaveResult =
    | { status: 'saved'; shortId: string; savedWidths: number; totalWidths: number }
    | { status: 'failed'; error: string }

export interface PageToolbarState {
    mode: PageToolbarMode
    inspect: PageToolbarInspectState
    heatmap: PageToolbarHeatmapState
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
