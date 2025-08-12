import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api, { ApiError, PaginatedResponse } from 'lib/api'

import { DataWarehouseSavedQueryDraft } from '~/types'

import type { draftsLogicType } from './draftsLogicType'
import { loaders } from 'kea-loaders'
import { HogQLQuery } from '~/queries/schema/schema-general'
import { lemonToast } from '@posthog/lemon-ui'
import posthog from 'posthog-js'
import { QueryTab } from './multitabEditorLogic'

export const draftsLogic = kea<draftsLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'draftsLogic']),

    actions({
        saveAsDraft: (query: HogQLQuery, viewId: string, tab: QueryTab) => ({
            query,
            viewId,
            tab,
        }),
        updateDraft: (draft: DataWarehouseSavedQueryDraft) => ({ draft }),
        saveOrUpdateDraft: (query: HogQLQuery, viewId?: string, draftId?: string, activeTab?: QueryTab) => ({
            query,
            viewId,
            draftId,
            activeTab,
        }),
        deleteDraft: (draftId: string, viewName?: string) => ({ draftId, viewName }),
        deleteDraftSuccess: (draftId: string, viewName?: string) => ({ draftId, viewName }),
        setDrafts: (drafts: DataWarehouseSavedQueryDraft[]) => ({ drafts }),
        renameDraft: (draftId: string, name: string) => ({ draftId, name }),
        saveAsDraftSuccess: (draft: DataWarehouseSavedQueryDraft, tab: QueryTab) => ({ draft, tab }),
    }),

    loaders(({ values }) => ({
        draftsResponse: [
            {} as PaginatedResponse<DataWarehouseSavedQueryDraft>,
            {
                loadDrafts: async () => {
                    const drafts = await api.dataWarehouseSavedQueryDrafts.list()

                    return drafts
                },
                loadMoreDrafts: async () => {
                    if (values.draftsResponse.next) {
                        const drafts = await api.get<PaginatedResponse<DataWarehouseSavedQueryDraft>>(
                            values.draftsResponse.next
                        )

                        return {
                            ...values.draftsResponse,
                            results: [...values.draftsResponse.results, ...drafts.results],
                            next: drafts.next,
                        }
                    }
                    return values.draftsResponse
                },
            },
        ],
    })),
    reducers({
        drafts: [
            [] as DataWarehouseSavedQueryDraft[],
            {
                setDrafts: (_, { drafts }) => drafts,
            },
        ],
    }),
    selectors({
        hasMoreDrafts: [(s) => [s.draftsResponse], (draftsResponse) => draftsResponse.next !== null],
    }),
    listeners(({ values, actions }) => ({
        loadDraftsSuccess: ({ draftsResponse }) => {
            actions.setDrafts(draftsResponse.results)
        },
        loadMoreDraftsSuccess: ({ draftsResponse }) => {
            actions.setDrafts(draftsResponse.results)
        },
        saveAsDraft: async ({ query, viewId, tab }) => {
            try {
                const draft = await api.dataWarehouseSavedQueryDrafts.create({
                    query,
                    saved_query_id: viewId,
                    edited_history_id: tab.view?.latest_history_id,
                })
                lemonToast.success('Draft saved')

                const newDrafts = [...values.drafts, draft]
                actions.setDrafts(newDrafts)
                actions.saveAsDraftSuccess(draft, tab)
            } catch (e) {
                const apiError = e as ApiError
                if (apiError) {
                    lemonToast.error(`Draft save failed: ${apiError.message}`)
                }
                posthog.captureException(e)
            }
        },
        updateDraft: async ({ draft }) => {
            try {
                const updatedDraft = await api.dataWarehouseSavedQueryDrafts.update(draft.id, draft)
                lemonToast.success('Draft updated')
                const newDrafts = values.drafts.map((d) => (d.id === draft.id ? updatedDraft : d))
                actions.setDrafts(newDrafts)
            } catch (e) {
                const apiError = e as ApiError
                if (apiError) {
                    lemonToast.error(`Draft update failed: ${apiError.message}`)
                }
                posthog.captureException(e)
            }
        },
        deleteDraft: async ({ draftId, viewName }) => {
            try {
                await api.dataWarehouseSavedQueryDrafts.delete(draftId)
                lemonToast.success('Draft deleted')

                const newDrafts = values.drafts.filter((draft) => draft.id !== draftId)
                actions.setDrafts(newDrafts)
                actions.deleteDraftSuccess(draftId, viewName)
            } catch (e) {
                const apiError = e as ApiError
                if (apiError) {
                    lemonToast.error(`Draft delete failed: ${apiError.message}`)
                }
                posthog.captureException(e)
            }
        },
        renameDraft: async ({ draftId, name }) => {
            await api.dataWarehouseSavedQueryDrafts.update(draftId, { name })
            actions.setDrafts(values.drafts.map((d) => (d.id === draftId ? { ...d, name } : d)))
        },
        saveOrUpdateDraft: async ({ query, viewId, draftId, activeTab }) => {
            if (draftId) {
                try {
                    const updatedDraft = await api.dataWarehouseSavedQueryDrafts.update(draftId, {
                        query,
                    })
                    lemonToast.success('Draft updated')
                    const newDrafts = values.drafts.map((d) => (d.id === draftId ? updatedDraft : d))
                    actions.setDrafts(newDrafts)
                } catch (e) {
                    const apiError = e as ApiError
                    if (apiError) {
                        lemonToast.error(`Draft update failed: ${apiError.message}`)
                    }
                    posthog.captureException(e)
                }
            } else {
                const existingDrafts = await api.dataWarehouseSavedQueryDrafts.list()
                const existingDraft = existingDrafts.results.find((draft) => draft.saved_query_id === viewId)

                if (existingDraft) {
                    actions.updateDraft({
                        ...existingDraft,
                        query,
                    })
                } else if (viewId && activeTab) {
                    actions.saveAsDraft(query, viewId, activeTab)
                }
            }
        },
    })),
])
