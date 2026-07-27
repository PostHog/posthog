import { ApiConfig } from '~/lib/api'

import {
    llmAnalyticsReviewQueueItemsCreate as aiObservabilityReviewQueueItemsCreate,
    llmAnalyticsReviewQueueItemsDestroy as aiObservabilityReviewQueueItemsDestroy,
    llmAnalyticsReviewQueueItemsList as aiObservabilityReviewQueueItemsList,
    llmAnalyticsReviewQueueItemsPartialUpdate as aiObservabilityReviewQueueItemsPartialUpdate,
    llmAnalyticsReviewQueuesCreate as aiObservabilityReviewQueuesCreate,
    llmAnalyticsReviewQueuesDestroy as aiObservabilityReviewQueuesDestroy,
    llmAnalyticsReviewQueuesList as aiObservabilityReviewQueuesList,
    llmAnalyticsReviewQueuesPartialUpdate as aiObservabilityReviewQueuesPartialUpdate,
    llmAnalyticsReviewQueuesRetrieve as aiObservabilityReviewQueuesRetrieve,
} from '../generated/api'
import type {
    LlmAnalyticsReviewQueueItemsListParams as AIObservabilityReviewQueueItemsListParams,
    LlmAnalyticsReviewQueuesListParams as AIObservabilityReviewQueuesListParams,
    PaginatedReviewQueueItemListApi,
    PaginatedReviewQueueListApi,
    PatchedReviewQueueItemUpdateApi,
    ReviewQueueApi,
    ReviewQueueCreateApi,
    ReviewQueueItemApi,
    ReviewQueueItemCreateApi,
} from '../generated/api.schemas'

function getCurrentProjectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

export const reviewQueuesApi = {
    listQueues(params?: AIObservabilityReviewQueuesListParams): Promise<PaginatedReviewQueueListApi> {
        return aiObservabilityReviewQueuesList(getCurrentProjectId(), params)
    },

    listQueuePickerOptions(): Promise<PaginatedReviewQueueListApi> {
        return aiObservabilityReviewQueuesList(getCurrentProjectId(), {
            order_by: 'name',
            limit: 1000,
        })
    },

    createQueue(data: ReviewQueueCreateApi): Promise<ReviewQueueApi> {
        return aiObservabilityReviewQueuesCreate(getCurrentProjectId(), data)
    },

    getQueue(id: string): Promise<ReviewQueueApi> {
        return aiObservabilityReviewQueuesRetrieve(getCurrentProjectId(), id)
    },

    updateQueue(id: string, data: ReviewQueueCreateApi): Promise<ReviewQueueApi> {
        return aiObservabilityReviewQueuesPartialUpdate(getCurrentProjectId(), id, data)
    },

    deleteQueue(id: string): Promise<void> {
        return aiObservabilityReviewQueuesDestroy(getCurrentProjectId(), id)
    },

    listQueueItems(params?: AIObservabilityReviewQueueItemsListParams): Promise<PaginatedReviewQueueItemListApi> {
        return aiObservabilityReviewQueueItemsList(getCurrentProjectId(), params)
    },

    createQueueItem(data: ReviewQueueItemCreateApi): Promise<ReviewQueueItemApi> {
        return aiObservabilityReviewQueueItemsCreate(getCurrentProjectId(), data)
    },

    updateQueueItem(id: string, data: PatchedReviewQueueItemUpdateApi): Promise<ReviewQueueItemApi> {
        return aiObservabilityReviewQueueItemsPartialUpdate(getCurrentProjectId(), id, data)
    },

    deleteQueueItem(id: string): Promise<void> {
        return aiObservabilityReviewQueueItemsDestroy(getCurrentProjectId(), id)
    },
}
