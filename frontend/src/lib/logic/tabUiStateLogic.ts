import { actions, kea, path, reducers, selectors } from 'kea'

import type { Node } from '~/queries/schema/schema-general'

import type { tabUiStateLogicType } from './tabUiStateLogicType'

const NO_TAB = '__no_tab__'

export type ExpandedRowsByTabAndVizKey = Record<string, Record<string, number[]>>
export type SavedQueriesByTabAndScene = Record<string, Record<string, Node>>
export type ChatDraftsByTab = Record<string, string>

export const tabUiStateLogic = kea<tabUiStateLogicType>([
    path(['lib', 'logic', 'tabUiStateLogic']),
    actions({
        toggleExpandedRow: (tabId: string | undefined, vizKey: string, rowIndex: number) => ({
            tabId: tabId ?? NO_TAB,
            vizKey,
            rowIndex,
        }),
        clearTabUiState: (tabId: string) => ({ tabId }),
        setSavedQueryForTab: (tabId: string | undefined, sceneKey: string, query: Node) => ({
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
            {} as ExpandedRowsByTabAndVizKey,
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
            {} as SavedQueriesByTabAndScene,
            {
                setSavedQueryForTab: (state, { tabId, sceneKey, query }) => ({
                    ...state,
                    [tabId]: { ...state[tabId], [sceneKey]: query },
                }),
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
            {} as ChatDraftsByTab,
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
