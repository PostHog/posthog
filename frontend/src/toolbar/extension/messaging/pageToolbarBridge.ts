import type {
    CommonFilters,
    HeatmapFilters,
    HeatmapFixedPositionMode,
    ScrollDepthPosthogJsError,
} from 'lib/components/heatmaps/types'

import type { SelectorMatchCounts } from '~/toolbar/shared/actions/SelectorCountContext'
import type { EventCategory } from '~/toolbar/shared/debug/eventCategories'
import type { PosthogDebugInfo } from '~/toolbar/shared/debug/posthogDebugInfo'
import type { ElementSelectorType } from '~/toolbar/shared/experiments/elementSelectorTypes'
import type { FlagInfo } from '~/toolbar/shared/flags/flagInfo'
import type { ActionForm, WebExperimentForm } from '~/toolbar/shared/types'
import type { WebVitalsMetrics } from '~/toolbar/shared/web-vitals/webVitalsToolbarLogic'
import type { ActionStepType, ElementType } from '~/types'

import type { PageActionsCommand } from '../logics/page/extensionPageActionsLogic'
import type { PageEventsCommand } from '../logics/page/extensionPageEventsLogic'
import type { PageExperimentsCommand } from '../logics/page/extensionPageExperimentsLogic'
import type { PageFlagsCommand } from '../logics/page/extensionPageFlagsLogic'
import type { PageHeatmapCommand } from '../logics/page/extensionPageHeatmapLogic'
import type { PageMoreCommand } from '../logics/page/extensionPageMoreLogic'
import type {
    PageInspectCommand,
    PageSessionCommand,
    PageSelectorsCommand,
} from '../logics/page/extensionPageToolbarLogic'
import type { PageWebVitalsCommand } from '../logics/page/extensionPageWebVitalsLogic'

/**
 * The content script runs the toolbar's own logics in the page, signed in with the extension's OAuth tokens. The panel
 * shows their controls. A port carries commands to the page and state back to the panel.
 */

// pinned: extension port name, the panel and an already injected content script must agree on it
export const PAGE_TOOLBAR_PORT = 'posthog-toolbar-page'

export type PageToolbarMode =
    | 'none'
    | 'heatmap'
    | 'inspect'
    | 'actions'
    | 'flags'
    | 'events'
    | 'web-vitals'
    | 'experiments'
    | 'more'

/** What the content script reads from the page's posthog-js through the page agent. */
export interface PageAnalyticsInfo {
    version: string | null
    scrollPropertiesDisabled: boolean
    /** The page's `scroll_root_selector`, which posthog-js measures scroll depth on instead of the window. */
    scrollRootSelector: string | string[] | null
    /** Null when the posthog-js version has no heatmaps module. */
    heatmapsEnabled: boolean | null
    /** Null when the posthog-js version has no web vitals module. */
    webVitalsEnabled: boolean | null
    webExperimentsDisabled: boolean
    /** The masking settings, with each value that isn't a string or a boolean replaced by `{}`. */
    sessionRecordingConfig: Record<string, unknown>
    sessionRecordingStatus: string | null
    featureFlags: PageFeatureFlagsSnapshot
}

/** The toolbar's debug info, read from the page's posthog-js when the user opens it. */
export interface PageDebugInfo extends PosthogDebugInfo {
    /** Null when the page's posthog-js has no surveys, or didn't answer in time. */
    surveysCount: number | null
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
    events: PageEventsCommand
    'web-vitals': PageWebVitalsCommand
    more: PageMoreCommand
    experiments: PageExperimentsCommand
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

/** The experiment form without `original_html_state`, which only the page uses to undo a preview. */
export type ExperimentFormDraft = Pick<WebExperimentForm, 'name' | 'variants'>

export type ExperimentSaveResult =
    | { status: 'saved'; experimentId: number; name: string | null }
    | { status: 'failed'; error: string }

export interface PageToolbarExperimentsState {
    loading: boolean
    experiments: { id: number; name: string | null }[]
    /** True when the page's posthog-js config sets `disable_web_experiments`. */
    webExperimentsDisabled: boolean
    selectedExperimentId: number | 'new' | null
    experimentForm: ExperimentFormDraft
    /** Goes up when the page changes the form itself, for example when the user picks an element for a transform. */
    formRevision: number
    /** The variant the page shows. */
    selectedVariant: string
    selectedElementType: ElementSelectorType
    /** The transform waiting for an element pick on the page. */
    inspectingElement: number | null
    addVariantAvailable: boolean
    removeVariantAvailable: boolean
    saving: boolean
    saveResult: ExperimentSaveResult | null
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

export interface DebugEventRow {
    uuid: string
    event: string
    timestamp: string
    pinned: boolean
}

export interface PageToolbarEventsState {
    /** False when the page has no `window.posthog`, so no events reach the debugger. */
    available: boolean
    selectedEventTypes: EventCategory[]
    hidePostHogProperties: boolean
    hidePostHogFlags: boolean
    relativeTimestamps: boolean
    isPaused: boolean
    bufferedCount: number
    totalCount: number
    filteredCount: number
    countsByType: Record<EventCategory, number>
    /** The newest filtered events, pinned ones first. */
    rows: DebugEventRow[]
    expandedEventId: string | null
    /** The expanded event's properties after the hide toggles. */
    expandedProperties: Record<string, unknown>
    /** The expanded event as captured, for copying. */
    expandedEventPayload: Record<string, unknown> | null
}

export interface PageToolbarWebVitalsState {
    autocaptureEnabled: boolean
    pathname: string
    localWebVitals: WebVitalsMetrics
    remoteWebVitals: WebVitalsMetrics
}

export interface PageToolbarMoreState {
    debugInfo: PageDebugInfo | null
    debugInfoLoading: boolean
    piiMaskingEnabled: boolean
    piiMaskingColor: string
    piiWarnings: string[]
    screenshot: {
        taking: boolean
        /** The page sends the preview image in its own `screenshot-preview` message, once. */
        open: boolean
        eventName: string
        suggestions: { id: string; name: string }[]
        suggestionsLoading: boolean
        selectedEventId: string | null
        uploading: boolean
        result: { status: 'uploaded' } | { status: 'failed'; error: string } | null
    }
}

export interface PageToolbarState {
    mode: PageToolbarMode
    inspect: PageToolbarInspectState
    /** Matches on the page for the selectors the panel asked about. `null` marks an invalid selector. */
    selectorCounts: Record<string, SelectorMatchCounts | null>
    heatmap: PageToolbarHeatmapState
    actions: PageToolbarActionsState
    flags: PageToolbarFlagsState
    events: PageToolbarEventsState
    webVitals: PageToolbarWebVitalsState
    experiments: PageToolbarExperimentsState
    more: PageToolbarMoreState
}

export type PageToolbarMessage =
    | { type: 'state'; state: PageToolbarState }
    /** The slices that changed since the last message. The rest keep their earlier value. */
    | { type: 'patch'; patch: Partial<PageToolbarState> }
    /** The page refreshed the tokens, which rotates the refresh token. */
    | { type: 'tokens'; tokens: PageToolbarTokens }
    | { type: 'token-expired' }
    | { type: 'screenshot-preview'; dataUrl: string }

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
