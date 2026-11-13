import type { FetchCandidate } from './collected-urls-record'
import type { PackedImageLocation, UrlCrawlHistoryItem } from './crawl-history'
import type { ImageFetchResult } from './image-fetcher'

/** Without a `pack`, the image is the one object of its reference. */
export interface StoredImage {
    pack?: PackedImageLocation
}

/**
 * Where the lane stores each fetched image. The image counts as handled only once the sink resolves: a rejection keeps
 * the URL unfinished, so it is fetched again.
 *
 * S3 expires an object by its creation time, so the lane refreshes an image that went the refresh interval of
 * `replay_core_v4::fetch_history` without one, and the image lives as long as the data that references it.
 */
export interface RefreshingImageSink {
    publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<StoredImage>
    /** Resets the age of the stored image of a reference, with no origin request. Resolves to null if none is stored. */
    refreshImage(candidate: FetchCandidate, history: UrlCrawlHistoryItem | undefined): Promise<StoredImage | null>
    indexStoredImage?(candidate: FetchCandidate, history: UrlCrawlHistoryItem): Promise<void>
}
