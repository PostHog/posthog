import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'

import { historyListLogicType } from './historyListLogicType'
import { dayjs } from 'lib/dayjs'
import React from 'react'
interface HistoryListLogicProps {
    type: 'FeatureFlag'
    id: number
}

export enum HistoryActions {
    FEATURE_FLAG_CREATED = 'FeatureFlag_created',
    FEATURE_FLAG_DESCRIPTION_CHANGED = 'FeatureFlag_name_changed',
    FEATURE_FLAG_IMPORTED = 'FeatureFlag_imported',
    FEATURE_FLAG_FILTERS_CHANGED = 'FeatureFlag_filters_changed',
    FEATURE_FLAG_SOFT_DELETED = 'FeatureFlag_deleted_added',
    FEATURE_FLAG_ROLLOUT_PERCENTAGE_CHANGED = 'FeatureFlag_rollout_percentage_changed',
    FEATURE_FLAG_ACTIVE_CHANGED = 'FeatureFlag_active_changed',
    FEATURE_FLAG_KEY_CHANGED = 'FeatureFlag_key_changed',
}

export interface HistoryDetail {
    id?: string | number
    key?: string
    name?: string
    filter?: string
    to?: string | Record<string, any> | boolean
}

export interface HistoryListItem {
    email?: string
    name?: string
    action: HistoryActions
    detail: HistoryDetail
    created_at: string
}

export interface HumanizedHistoryListItem {
    email?: string
    name?: string
    description: string | JSX.Element
    created_at: dayjs.Dayjs
}

const actionsMapping: {
    [key in HistoryActions]: (detail: HistoryDetail) => string | JSX.Element
} = {
    [HistoryActions.FEATURE_FLAG_CREATED]: () => `created the flag`,
    [HistoryActions.FEATURE_FLAG_DESCRIPTION_CHANGED]: (detail) =>
        `changed the description of the flag to: ${detail.to}`,
    [HistoryActions.FEATURE_FLAG_ACTIVE_CHANGED]: (detail) => (detail.to ? 'enabled the flag' : 'disabled the flag'),
    [HistoryActions.FEATURE_FLAG_IMPORTED]: () => `imported the flag`,
    [HistoryActions.FEATURE_FLAG_FILTERS_CHANGED]: function onChangedFilter(detail) {
        return (
            <>
                changed the filters to <code>{JSON.stringify(detail.to)}</code>
            </>
        )
    },
    [HistoryActions.FEATURE_FLAG_SOFT_DELETED]: () => `deleted the flag`,
    [HistoryActions.FEATURE_FLAG_ROLLOUT_PERCENTAGE_CHANGED]: (detail) => `changed rollout percentage to ${detail.to}`,
    [HistoryActions.FEATURE_FLAG_KEY_CHANGED]: (detail) => `changed the flag key to ${detail.to}`,
}

function descriptionFrom(historyListItem: HistoryListItem): string | JSX.Element | null {
    const mapping = actionsMapping[historyListItem.action]
    return (mapping && mapping(historyListItem.detail)) || null
}

function humanize(results: HistoryListItem[]): HumanizedHistoryListItem[] {
    return (results || []).reduce((acc, historyListItem) => {
        const humanized = descriptionFrom(historyListItem)
        if (humanized !== null) {
            acc.push({
                email: historyListItem.email,
                name: historyListItem.name,
                description: humanized,
                created_at: dayjs(historyListItem.created_at),
            })
        }
        return acc
    }, [] as HumanizedHistoryListItem[])
}

export const historyListLogic = kea<historyListLogicType<HistoryListLogicProps, HumanizedHistoryListItem>>({
    path: (key) => ['lib', 'components', 'HistoryList', 'historyList', 'logic', key],
    props: {} as HistoryListLogicProps,
    key: ({ id, type }) => `history/${type}/${id}`,
    loaders: ({ props }) => ({
        history: [
            [] as HumanizedHistoryListItem[],
            {
                fetchHistory: async () => {
                    const apiResponse: PaginatedResponse<HistoryListItem> = await api.get(
                        `/api/projects/@current/feature_flags/${props.id}/history`
                    )
                    return humanize(apiResponse?.results)
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchHistory()
        },
    }),
})
