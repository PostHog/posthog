import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { Node } from '~/queries/schema/schema-general'

import type { tabUiStateLogicType } from './tabUiStateLogicType'

const NO_TAB = '__no_tab__'

export const TAB_UI_STATE_STORAGE_KEY = 'ph_tab_ui_state'
// Bump when PersistedShape changes in a backwards-incompatible way (renamed/removed
// key, changed value type). Old payloads are discarded on read — no migration needed.
export const TAB_UI_STATE_STORAGE_VERSION = 1
export const TAB_UI_STATE_TTL_MS = 30 * 24 * 60 * 60 * 1000

export type ExpandedRowsByTabAndVizKey = Record<string, Record<string, number[]>>
export type SavedQueriesByTabAndScene = Record<string, Record<string, Node>>
export type ChatDraftsByTab = Record<string, string>

// 🚨 Changing this shape (rename/remove key, change a value type) requires
// bumping TAB_UI_STATE_STORAGE_VERSION so stale payloads in user browsers
// are discarded on read instead of crashing consumers.
type PersistedShape = {
    expandedRowsByTabAndVizKey: ExpandedRowsByTabAndVizKey
    savedQueriesByTabAndScene: SavedQueriesByTabAndScene
    chatDraftsByTab: ChatDraftsByTab
}

type PersistedEnvelope = {
    version: number
    updatedAt: number
    state: PersistedShape
}

const EMPTY_PERSISTED: PersistedShape = {
    expandedRowsByTabAndVizKey: {},
    savedQueriesByTabAndScene: {},
    chatDraftsByTab: {},
}

function getStorage(): Storage | null {
    try {
        if (typeof window === 'undefined') {
            return null
        }
        return window.localStorage
    } catch {
        return null
    }
}

export function readPersistedState(): PersistedShape {
    const storage = getStorage()
    if (!storage) {
        return EMPTY_PERSISTED
    }
    let raw: string | null
    try {
        raw = storage.getItem(TAB_UI_STATE_STORAGE_KEY)
    } catch {
        return EMPTY_PERSISTED
    }
    if (!raw) {
        return EMPTY_PERSISTED
    }
    let parsed: PersistedEnvelope
    try {
        parsed = JSON.parse(raw) as PersistedEnvelope
    } catch {
        return EMPTY_PERSISTED
    }
    if (
        !parsed ||
        typeof parsed !== 'object' ||
        parsed.version !== TAB_UI_STATE_STORAGE_VERSION ||
        typeof parsed.updatedAt !== 'number' ||
        Date.now() - parsed.updatedAt > TAB_UI_STATE_TTL_MS ||
        !parsed.state ||
        typeof parsed.state !== 'object'
    ) {
        return EMPTY_PERSISTED
    }
    return {
        expandedRowsByTabAndVizKey: parsed.state.expandedRowsByTabAndVizKey ?? {},
        savedQueriesByTabAndScene: parsed.state.savedQueriesByTabAndScene ?? {},
        chatDraftsByTab: parsed.state.chatDraftsByTab ?? {},
    }
}

let writeWarned = false

function writePersistedState(state: PersistedShape): void {
    const storage = getStorage()
    if (!storage) {
        return
    }
    const envelope: PersistedEnvelope = {
        version: TAB_UI_STATE_STORAGE_VERSION,
        updatedAt: Date.now(),
        state,
    }
    try {
        storage.setItem(TAB_UI_STATE_STORAGE_KEY, JSON.stringify(envelope))
    } catch (error) {
        if (!writeWarned) {
            writeWarned = true
            console.warn('[tabUiStateLogic] failed to persist tab UI state', error)
        }
    }
}

const INITIAL_PERSISTED = readPersistedState()

export const tabUiStateLogic = kea<tabUiStateLogicType>([
    path(['lib', 'logic', 'tabUiStateLogic']),
    actions({
        toggleExpandedRow: (tabId: string | undefined, vizKey: string, rowIndex: number) => ({
            tabId: tabId ?? NO_TAB,
            vizKey,
            rowIndex,
        }),
        clearTabUiState: (tabId: string) => ({ tabId }),
        setSavedQueryForTab: (tabId: string | undefined, sceneKey: string, query: Node | null) => ({
            tabId: tabId ?? NO_TAB,
            sceneKey,
            query,
        }),
        setChatDraftForTab: (tabId: string | undefined, draft: string) => ({
            tabId: tabId ?? NO_TAB,
            draft,
        }),
    }),
    reducers({
        expandedRowsByTabAndVizKey: [
            INITIAL_PERSISTED.expandedRowsByTabAndVizKey as ExpandedRowsByTabAndVizKey,
            {
                toggleExpandedRow: (state, { tabId, vizKey, rowIndex }) => {
                    const tabState = state[tabId] ?? {}
                    const existing = tabState[vizKey] ?? []
                    const next = existing.includes(rowIndex)
                        ? existing.filter((r: number) => r !== rowIndex)
                        : [...existing, rowIndex]
                    return { ...state, [tabId]: { ...tabState, [vizKey]: next } }
                },
                clearTabUiState: (state, { tabId }) => {
                    if (!(tabId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[tabId]
                    return next
                },
            },
        ],
        savedQueriesByTabAndScene: [
            INITIAL_PERSISTED.savedQueriesByTabAndScene as SavedQueriesByTabAndScene,
            {
                setSavedQueryForTab: (state, { tabId, sceneKey, query }) => {
                    if (query === null) {
                        // Clear: drop the scene slot, and the whole tab entry if it becomes empty.
                        const tabState = state[tabId]
                        if (!tabState || !(sceneKey in tabState)) {
                            return state
                        }
                        const nextTabState = { ...tabState }
                        delete nextTabState[sceneKey]
                        if (Object.keys(nextTabState).length === 0) {
                            const next = { ...state }
                            delete next[tabId]
                            return next
                        }
                        return { ...state, [tabId]: nextTabState }
                    }
                    return {
                        ...state,
                        [tabId]: { ...state[tabId], [sceneKey]: query },
                    }
                },
                clearTabUiState: (state, { tabId }) => {
                    if (!(tabId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[tabId]
                    return next
                },
            },
        ],
        chatDraftsByTab: [
            INITIAL_PERSISTED.chatDraftsByTab as ChatDraftsByTab,
            {
                setChatDraftForTab: (state, { tabId, draft }) => {
                    if (draft === '') {
                        if (!(tabId in state)) {
                            return state
                        }
                        const next = { ...state }
                        delete next[tabId]
                        return next
                    }
                    return { ...state, [tabId]: draft }
                },
                clearTabUiState: (state, { tabId }) => {
                    if (!(tabId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[tabId]
                    return next
                },
            },
        ],
    }),
    listeners(({ values }) => {
        const persist = (): void => {
            writePersistedState({
                expandedRowsByTabAndVizKey: values.expandedRowsByTabAndVizKey,
                savedQueriesByTabAndScene: values.savedQueriesByTabAndScene,
                chatDraftsByTab: values.chatDraftsByTab,
            })
        }
        return {
            toggleExpandedRow: persist,
            clearTabUiState: persist,
            setSavedQueryForTab: persist,
            setChatDraftForTab: persist,
        }
    }),
    selectors({
        expandedRowsFor: [
            (s) => [s.expandedRowsByTabAndVizKey],
            (state): ((tabId: string | undefined, vizKey: string) => number[]) =>
                (tabId, vizKey) =>
                    state[tabId ?? NO_TAB]?.[vizKey] ?? [],
        ],
        savedQueryFor: [
            (s) => [s.savedQueriesByTabAndScene],
            (state): ((tabId: string | undefined, sceneKey: string) => Node | null) =>
                (tabId, sceneKey) =>
                    state[tabId ?? NO_TAB]?.[sceneKey] ?? null,
        ],
        chatDraftFor: [
            (s) => [s.chatDraftsByTab],
            (state): ((tabId: string | undefined) => string) =>
                (tabId) =>
                    state[tabId ?? NO_TAB] ?? '',
        ],
    }),
])
