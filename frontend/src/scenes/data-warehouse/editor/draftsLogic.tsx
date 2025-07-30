import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api, { PaginatedResponse } from 'lib/api'

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
        deleteDraft: (draftId: string, successCallback?: () => void) => ({ draftId, successCallback }),
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
            const draft = await api.dataWarehouseSavedQueryDrafts.create({
                query,
                saved_query_id: viewId,
                edited_history_id: tab.view?.latest_history_id,
            })
            lemonToast.success('Draft saved')

            const newDrafts = [...values.drafts, draft]
            actions.setDrafts(newDrafts)
            actions.saveAsDraftSuccess(draft, tab)
        },
        updateDraft: async ({ draft }) => {
            const updatedDraft = await api.dataWarehouseSavedQueryDrafts.update(draft.id, draft)
            lemonToast.success('Draft updated')
            const newDrafts = values.drafts.map((d) => (d.id === draft.id ? updatedDraft : d))
            actions.setDrafts(newDrafts)
        },
        deleteDraft: async ({ draftId }) => {
            try {
                await api.dataWarehouseSavedQueryDrafts.delete(draftId)
                lemonToast.success('Draft deleted')

                const newDrafts = values.drafts.filter((draft) => draft.id !== draftId)
                actions.setDrafts(newDrafts)
            } catch (e) {
                lemonToast.error('Failed to delete draft')
                posthog.captureException(e)
            }
        },
        renameDraft: async ({ draftId, name }) => {
            await api.dataWarehouseSavedQueryDrafts.update(draftId, { name })
            actions.setDrafts(values.drafts.map((d) => (d.id === draftId ? { ...d, name } : d)))
        },
        saveOrUpdateDraft: async ({ query, viewId, draftId, activeTab }) => {
            try {
                if (draftId) {
                    const updatedDraft = await api.dataWarehouseSavedQueryDrafts.update(draftId, {
                        query,
                    })
                    lemonToast.success('Draft updated')
                    const newDrafts = values.drafts.map((d) => (d.id === draftId ? updatedDraft : d))
                    actions.setDrafts(newDrafts)
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
            } catch (e) {
                lemonToast.error('Failed to save draft')
                posthog.captureException(e)
            }
        },
    })),
])
