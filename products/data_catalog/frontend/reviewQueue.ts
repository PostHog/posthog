import type { UserType } from '~/types'

import type { DataCatalogMetricApi } from './generated/api.schemas'

/** A metric needs review until it is approved and matches its source insight. */
export function needsReview(metric: DataCatalogMetricApi): boolean {
    return metric.status !== 'approved' || !!metric.is_drifted
}

function isMine(metric: DataCatalogMetricApi, user: Pick<UserType, 'uuid' | 'email'> | null): boolean {
    if (!user) {
        return false
    }
    // created_by is SET_NULL on the model, so a deleted creator arrives as null despite the serializer type.
    return metric.created_by?.uuid === user.uuid || (!!metric.owner && metric.owner === user.email)
}

// Drift comes first because agents answer with a drifted metric until someone refreshes it.
function priority(metric: DataCatalogMetricApi, user: Pick<UserType, 'uuid' | 'email'> | null): number {
    const mine = isMine(metric, user)
    if (metric.is_drifted) {
        return mine ? 0 : 1
    }
    if (mine) {
        return 2
    }
    return metric.created_source === 'ai_generated' ? 3 : 4
}

/**
 * Orders the review queue: your drifted metrics, other drifted metrics, your proposals,
 * AI proposals by confidence, then the rest. Newer metrics come first inside a group.
 */
export function compareReviewQueue(
    user: Pick<UserType, 'uuid' | 'email'> | null
): (a: DataCatalogMetricApi, b: DataCatalogMetricApi) => number {
    return (a, b) => {
        const byPriority = priority(a, user) - priority(b, user)
        if (byPriority !== 0) {
            return byPriority
        }
        if (priority(a, user) === 3) {
            const byConfidence = (b.confidence ?? 0) - (a.confidence ?? 0)
            if (byConfidence !== 0) {
                return byConfidence
            }
        }
        return (b.created_at ?? '').localeCompare(a.created_at ?? '')
    }
}
