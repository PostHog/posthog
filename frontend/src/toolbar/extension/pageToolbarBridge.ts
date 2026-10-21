import type {
    CommonFilters,
    HeatmapFilters,
    HeatmapFixedPositionMode,
    ScrollDepthPosthogJsError,
} from 'lib/components/heatmaps/types'

import type { ActionForm } from '~/toolbar/types'
import type { ActionStepType, ElementType } from '~/types'

import type { PageActionsCommand } from './extensionPageActionsLogic'
import type { PageFlagsCommand } from './extensionPageFlagsLogic'
import type { PageHeatmapCommand } from './extensionPageHeatmapLogic'
import type { PageInspectCommand, PageSessionCommand, PageSelectorsCommand } from './extensionPageToolbarLogic'

/**
 * The content script runs the toolbar's own logics in the page, signed in with the extension's OAuth tokens. The panel
 * shows their controls. A port carries commands to the page and state back to the panel.
 */

// pinned: extension port name, the panel and an already injected content script must agree on it
export const PAGE_TOOLBAR_PORT = 'posthog-toolbar-page'

export type PageToolbarMode = 'none' | 'heatmap' | 'inspect' | 'actions' | 'flags'

/** What the content script reads from the page's posthog-js through the page agent. */
export interface PageAnalyticsInfo {
    version: string | null
    scrollPropertiesDisabled: boolean
    /** The page's `scroll_root_selector`, which posthog-js measures scroll depth on instead of the window. */
    scrollRootSelector: string | string[] | null
    /** Null when the posthog-js version has no heatmaps module. */
    heatmapsEnabled: boolean | null
    featureFlags: PageFeatureFlagsSnapshot
}

export interface PageFeatureFlagsSnapshot {
    overrides: Record<string, string | boolean>
    variants: Record<string, string | boolean>
    groups: Record<string, string>
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
    selectors: PageSelectorsCommand
    heatmap: PageHeatmapCommand
    actions: PageActionsCommand
    flags: PageFlagsCommand
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

export type ActionSaveResult =
    | { status: 'saved'; actionId: number; name: string | null }
    | { status: 'failed'; error: string }

export interface PageToolbarActionsState {
    allActionsLoading: boolean
    actions: { id: number; name: string | null }[]
    selectedActionId: number | 'new' | null
    actionForm: ActionForm
    /** Goes up when the page changes the form itself, for example when the user picks an element for a step. */
    formRevision: number
    actionFormElementsChains: Record<number, ElementType[]>
    inspectingElement: number | null
    saving: boolean
    saveResult: ActionSaveResult | null
}

export interface FlagInfo {
    key: string
    id: number | null
    /** The value PostHog evaluates for the signed-in user. Choosing it again removes the override. */
    value: string | boolean
    currentValue: string | boolean
    hasOverride: boolean
    variants: { key: string; name: string | null; rolloutPercentage: number | null }[]
    payloadOverride: unknown
}

export interface PageToolbarFlagsState {
    /** False when the page has no `window.posthog`, so overrides can't reach it. */
    available: boolean
    loading: boolean
    flags: FlagInfo[]
    countFlagsOverridden: number
    impersonatedDistinctId: string | null
    payloadErrors: Record<string, string | null>
    /** True from the moment the page sends an override until the page's posthog-js applies it or the wait times out. */
    mutationPending: boolean
    mutationError: string | null
    /** Goes up when the page finishes applying an override, whether it worked or not. */
    mutationRevision: number
}

export interface PageToolbarState {
    mode: PageToolbarMode
    inspect: PageToolbarInspectState
    /** Matches on the page for the selectors the panel asked about. `null` marks an invalid selector. */
    selectorCounts: Record<string, number | null>
    heatmap: PageToolbarHeatmapState
    actions: PageToolbarActionsState
    flags: PageToolbarFlagsState
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
