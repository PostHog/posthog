import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api, { PaginatedResponse } from 'lib/api'

import { DataWarehouseSavedQueryDraft } from '~/types'

import type { draftsLogicType } from './draftsLogicType'
import { loaders } from 'kea-loaders'
import { HogQLQuery } from '~/queries/schema/schema-general'
import { lemonToast } from '@posthog/lemon-ui'
import posthog from 'posthog-js'

export const draftsLogic = kea<draftsLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'draftsLogic']),

    actions({
        saveAsDraft: (
            query: HogQLQuery,
            viewId: string,
            successCallback?: (draft: DataWarehouseSavedQueryDraft) => void,
            editedHistoryId?: string
        ) => ({
            query,
            viewId,
            successCallback,
            editedHistoryId,
        }),
        updateDraft: (draft: DataWarehouseSavedQueryDraft) => ({ draft }),
        saveOrUpdateDraft: (query: HogQLQuery, viewId?: string, draftId?: string, editedHistoryId?: string) => ({
            query,
            viewId,
            draftId,
            editedHistoryId,
        }),
        deleteDraft: (draftId: string, successCallback?: () => void) => ({ draftId, successCallback }),
        setDrafts: (drafts: DataWarehouseSavedQueryDraft[]) => ({ drafts }),
        renameDraft: (draftId: string, name: string) => ({ draftId, name }),
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
        saveAsDraft: async ({ query, viewId, successCallback, editedHistoryId }) => {
            const draft = await api.dataWarehouseSavedQueryDrafts.create({
                query,
                saved_query_id: viewId,
                edited_history_id: editedHistoryId,
            })
            lemonToast.success('Draft saved')
            successCallback && successCallback(draft)

            const newDrafts = [...values.drafts, draft]
            actions.setDrafts(newDrafts)
        },
        updateDraft: async ({ draft }) => {
            await api.dataWarehouseSavedQueryDrafts.update(draft.id, draft)
            lemonToast.success('Draft updated')
            const newDrafts = values.drafts.map((d) => (d.id === draft.id ? draft : d))
            actions.setDrafts(newDrafts)
        },
        deleteDraft: async ({ draftId, successCallback }) => {
            try {
                await api.dataWarehouseSavedQueryDrafts.delete(draftId)
                lemonToast.success('Draft deleted')
                successCallback && successCallback()

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
        saveOrUpdateDraft: async ({
            query,
            viewId,
            draftId,
            editedHistoryId,
        }: {
            query: HogQLQuery
            viewId?: string
            draftId?: string
            editedHistoryId?: string
        }) => {
            try {
                if (draftId) {
                    await api.dataWarehouseSavedQueryDrafts.update(draftId, {
                        query,
                    })
                    lemonToast.success('Draft updated')
                    const newDrafts = values.drafts.map((d) => (d.id === draftId ? { ...d, query } : d))
                    actions.setDrafts(newDrafts)
                } else {
                    const existingDrafts = await api.dataWarehouseSavedQueryDrafts.list()
                    const existingDraft = existingDrafts.results.find((draft) => draft.saved_query_id === viewId)

                    if (existingDraft) {
                        actions.updateDraft({
                            ...existingDraft,
                            query,
                        })
                        lemonToast.success('Draft updated')
                    } else if (viewId) {
                        actions.saveAsDraft(query, viewId, undefined, editedHistoryId)
                        lemonToast.success('Draft saved')
                    }
                }
            } catch (e) {
                lemonToast.error('Failed to save draft')
                posthog.captureException(e)
            }
        },
    })),
])
