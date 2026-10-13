import type { ElementsEventType } from '~/toolbar/types'
import type { FragileSelectorResult } from '~/toolbar/utils/selectorQuality'
import type { ActionStepType } from '~/types'

// pinned: extension message source, the popup and an already injected content script must agree on it
export const CONTENT_MESSAGE_SOURCE = 'posthog-toolbar-extension'

// pinned: extension storage key, the content script writes it and the popup reads it
export const SELECTED_ELEMENT_STORAGE_KEY = 'posthogSelectedElement'

export type ContentCommand =
    | { type: 'get-status' }
    | { type: 'start-element-selection'; dataAttributes: string[] }
    | { type: 'stop-element-selection' }
    | { type: 'show-heatmap'; elementStats: ElementsEventType[]; dataAttributes: string[] }
    | { type: 'hide-heatmap' }

export interface ContentMessage {
    source: typeof CONTENT_MESSAGE_SOURCE
    command: ContentCommand
}

/** The content script answers every command with its state after the command. */
export interface ContentStatus {
    selecting: boolean
    /** Null when no heatmap shows on the page. */
    heatmapElementCount: number | null
}

export const IDLE_CONTENT_STATUS: ContentStatus = { selecting: false, heatmapElementCount: null }

/** The content script stores the element the user picks, because the popup closes when the user clicks the page. */
export interface SelectedElement {
    pageUrl: string
    actionStep: ActionStepType
    selectorQuality: FragileSelectorResult | null
}

const COMMAND_TYPES: ContentCommand['type'][] = [
    'get-status',
    'start-element-selection',
    'stop-element-selection',
    'show-heatmap',
    'hide-heatmap',
]

export function isContentMessage(message: unknown): message is ContentMessage {
    if (!message || typeof message !== 'object') {
        return false
    }
    const { source, command } = message as Partial<ContentMessage>
    return (
        source === CONTENT_MESSAGE_SOURCE &&
        !!command &&
        typeof command === 'object' &&
        COMMAND_TYPES.includes(command.type)
    )
}

export function isSelectedElement(value: unknown): value is SelectedElement {
    if (!value || typeof value !== 'object') {
        return false
    }
    const { pageUrl, actionStep } = value as Partial<SelectedElement>
    return typeof pageUrl === 'string' && !!actionStep && typeof actionStep === 'object'
}
