import { combineUrl } from 'kea-router'

import { isObject } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { PlaylistRecordingsCounts } from '~/types'

export interface CollectionCounts {
    total: number | null
    unwatched: number
}

export function isPlaylistRecordingsCounts(x: unknown): x is PlaylistRecordingsCounts {
    return isObject(x) && ('collection' in x || 'saved_filters' in x)
}

export function getCollectionCounts(recordingsCounts: unknown): CollectionCounts | null {
    if (!isPlaylistRecordingsCounts(recordingsCounts)) {
        return null
    }
    const hasResults = recordingsCounts.collection.count !== null || recordingsCounts.saved_filters?.count !== null
    if (!hasResults) {
        return null
    }
    const total = recordingsCounts.collection.count ?? recordingsCounts.saved_filters?.count ?? null
    const watched = recordingsCounts.collection.watched_count ?? recordingsCounts.saved_filters?.watched_count ?? 0
    return { total, unwatched: Math.max(0, (total ?? 0) - watched) }
}

export function watchNextUrl(shortId: string): string {
    return combineUrl(urls.replayPlaylist(shortId), { watchNext: true }).url
}
