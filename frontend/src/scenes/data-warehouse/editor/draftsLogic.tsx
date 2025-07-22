import { actions, kea, listeners, path } from 'kea'
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
        saveAsDraft: (query: HogQLQuery, viewId: string, successCallback?: (draftId: string) => void) => ({
            query,
            viewId,
            successCallback,
        }),
        updateDraft: (draft: DataWarehouseSavedQueryDraft) => ({ draft }),
        saveOrUpdateDraft: (query: HogQLQuery, viewId: string, draftId?: string) => ({ query, viewId, draftId }),
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
    listeners(() => ({
        saveAsDraft: async ({ query, viewId, successCallback }) => {
            const draft = await api.dataWarehouseSavedQueryDrafts.create({
                query,
                saved_query_id: viewId,
            })
            lemonToast.success('Draft saved')
            successCallback && successCallback(draft.id)
        },
        updateDraft: async ({ draft }) => {
            await api.dataWarehouseSavedQueryDrafts.update(draft.id, draft)
            lemonToast.success('Draft updated')
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
                    // Update existing draft
                    await api.dataWarehouseSavedQueryDrafts.update(draftId, {
                        query,
                    })
                    lemonToast.success('Draft updated')
                } else {
                    // Try to find existing draft first
                    const existingDrafts = await api.dataWarehouseSavedQueryDrafts.list()
                    const existingDraft = existingDrafts.results.find((draft) => draft.saved_query_id === viewId)

                    if (existingDraft) {
                        // Update existing draft
                        await api.dataWarehouseSavedQueryDrafts.update(existingDraft.id, {
                            query,
                        })
                        lemonToast.success('Draft updated')
                    } else {
                        // Create new draft
                        await api.dataWarehouseSavedQueryDrafts.create({
                            query,
                            saved_query_id: viewId,
                        })
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
