import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'

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
            successCallback?: (draft: DataWarehouseSavedQueryDraft) => void
        ) => ({
            query,
            viewId,
            successCallback,
        }),
        updateDraft: (draft: DataWarehouseSavedQueryDraft) => ({ draft }),
        saveOrUpdateDraft: (query: HogQLQuery, viewId: string, draftId?: string) => ({ query, viewId, draftId }),
        deleteDraft: (draftId: string, successCallback?: () => void) => ({ draftId, successCallback }),
        setDrafts: (drafts: DataWarehouseSavedQueryDraft[]) => ({ drafts }),
    }),

    loaders({
        drafts: [
            [] as DataWarehouseSavedQueryDraft[],
            {
                loadDrafts: async () => {
                    const drafts = await api.dataWarehouseSavedQueryDrafts.list()
                    return drafts.results
                },
            },
        ],
    }),
    reducers({
        drafts: [
            [] as DataWarehouseSavedQueryDraft[],
            {
                setDrafts: (_, { drafts }) => drafts,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        saveAsDraft: async ({ query, viewId, successCallback }) => {
            const draft = await api.dataWarehouseSavedQueryDrafts.create({
                query,
                saved_query_id: viewId,
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

        saveOrUpdateDraft: async ({
            query,
            viewId,
            draftId,
        }: {
            query: HogQLQuery
            viewId: string
            draftId?: string
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
                    } else {
                        actions.saveAsDraft(query, viewId)
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
