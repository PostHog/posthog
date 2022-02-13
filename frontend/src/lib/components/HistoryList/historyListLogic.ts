import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'

import { historyListLogicType } from './historyListLogicType'
import { ApiError } from '~/types'
import { dayjs } from 'lib/dayjs'
interface HistoryListLogicProps {
    type: 'FeatureFlag'
    id: number
}

export enum HistoryActions {
    CREATED_FEATURE_FLAG = 'created_feature_flag',
    ADD_DESCRIPTION_TO_FLAG = 'add_description_to_flag',
    ADD_FILTER_TO_FLAG = 'add_filter_to_flag',
    DISABLED_FILTER = 'disabled_filter',
}

export interface HistoryDetail {
    id?: string | number
    description?: string
    name?: string
    filter?: string
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

const actionsMapping: { [key in HistoryActions]: (detail: HistoryDetail) => string } = {
    [HistoryActions.CREATED_FEATURE_FLAG]: (detail) => `created the feature flag: ${detail.name}`,
    [HistoryActions.ADD_DESCRIPTION_TO_FLAG]: (detail) => `added "${detail.description}" as the flag description`,
    [HistoryActions.ADD_FILTER_TO_FLAG]: () => 'added a filter to the flag',
    [HistoryActions.DISABLED_FILTER]: () => 'disabled the filter',
}

function descriptionFrom(historyListItem: HistoryListItem): string | JSX.Element | null {
    const mapping = actionsMapping[historyListItem.action]
    return (mapping && mapping(historyListItem.detail)) || null
}

function humanize(results: HistoryListItem[]): HumanizedHistoryListItem[] {
    return results.reduce((acc, historyListItem) => {
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
