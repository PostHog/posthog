import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'

import { historyListLogicType } from './historyListLogicType'
import { ApiError } from '~/types'
import { dayjs } from 'lib/dayjs'
import React from 'react'
interface HistoryListLogicProps {
    type: 'FeatureFlag'
    id: number
}

export enum HistoryActions {
    CREATED_FEATURE_FLAG = 'created_FeatureFlag',
    CHANGED_DESCRIPTION_ON_FLAG = 'changed_name_on_FeatureFlag',
    HISTORY_HOG_IMPORTED_FLAG = 'history_hog_imported_FeatureFlag',
    CHANGED_FILTERS_ON_FLAG = 'changed_filters_on_FeatureFlag',
    SOFT_DELETED_FLAG = 'added_deleted_to_FeatureFlag',
    CHANGED_ROLLOUT_PERCENTAGE_ON_FLAG = 'changed_rollout_percentage_on_FeatureFlag',
    CHANGED_ACTIVE_ON_FLAG = 'changed_active_on_FeatureFlag',
    CHANGED_KEY_ON_FLAG = 'changed_key_on_FeatureFlag',
}

export interface HistoryDetail {
    id?: string | number
    key?: string
    name?: string
    filter?: string
    to?: string | Record<string, any>
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

const actionsMapping: { [key in HistoryActions]: (detail: HistoryDetail) => string | JSX.Element } = {
    [HistoryActions.CREATED_FEATURE_FLAG]: () => `created the flag`,
    [HistoryActions.CHANGED_DESCRIPTION_ON_FLAG]: (detail) => `changed the description of the flag to: ${detail.to}`,
    [HistoryActions.CHANGED_ACTIVE_ON_FLAG]: (detail) => (detail.to ? 'enabled the flag' : 'disabled the flag'),
    [HistoryActions.HISTORY_HOG_IMPORTED_FLAG]: () => `imported the flag`,
    [HistoryActions.CHANGED_FILTERS_ON_FLAG]: function onChangedFilter(detail) {
        return (
            <>
                changed the filters to <pre>{JSON.stringify(detail.to)}</pre>
            </>
        )
    },
    [HistoryActions.SOFT_DELETED_FLAG]: () => `deleted the flag`,
    [HistoryActions.CHANGED_ROLLOUT_PERCENTAGE_ON_FLAG]: (detail) => `changed rollout percentage to ${detail.to}`,
    [HistoryActions.CHANGED_KEY_ON_FLAG]: (detail) => `changed the flag key to ${detail.to}`,
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

/**
 * Since we may be tracking history for a number of items on the same page
 * E.g. insights on a dashboard
 * We have a single logic for all items of a type which caches its responses
 *
 * TODO It may be slightly more complex than necessary as paging and filtering are likely to follow soon
 */
export const historyListLogic = kea<
    historyListLogicType<HistoryListItem, HistoryListLogicProps, HumanizedHistoryListItem>
>({
    path: ['lib', 'components', 'HistoryList', 'historyList', 'logic'],
    props: {} as HistoryListLogicProps,
    key: (props) => `history/${props.type}`,
    actions: {
        fetchHistory: () => {},
        fetchHistorySuccess: (apiResponse: PaginatedResponse<HistoryListItem>) => apiResponse,
        fetchHistoryFailure: (error: ApiError) => ({ error }),
    },
    reducers: ({ props }) => ({
        isLoading: [
            false,
            {
                fetchHistory: () => true,
                fetchHistorySuccess: () => false,
                fetchHistoryFailure: () => false,
            },
        ],
        history: [
            {} as Record<number, HumanizedHistoryListItem[]>,
            {
                fetchHistorySuccess: (state, { results }) => {
                    const newForId = [...(state[props.id] || []), ...humanize(results)]
                    return { ...state, [props.id]: newForId }
                },
            },
        ],
    }),
    listeners: ({ props, actions }) => ({
        fetchHistory: async (_, breakpoint) => {
            let apiResponse: PaginatedResponse<HistoryListItem>

            try {
                apiResponse = await api.get(`/api/projects/@current/feature_flags/${props.id}/history`)
                breakpoint()
                actions.fetchHistorySuccess(apiResponse)
            } catch (error) {
                actions.fetchHistoryFailure(error as ApiError)
                return
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchHistory()
        },
    }),
})
