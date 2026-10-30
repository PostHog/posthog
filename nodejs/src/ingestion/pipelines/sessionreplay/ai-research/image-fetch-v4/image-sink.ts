import type { FetchCandidate } from './collected-urls-record'
import type { ImageFetchResult } from './image-fetcher'

/**
 * Where the lane stores each fetched image. The image counts as handled only once the sink resolves: a rejection keeps
 * the URL unfinished, so it is fetched again.
 *
 * S3 expires an object by its creation time, so the lane refreshes an image that went `refreshIntervalMs` without one,
 * and the image lives as long as the data that references it.
 */
export interface RefreshingImageSink {
    readonly refreshIntervalMs: number
    publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<void>
    /** Resets the age of the stored image of a reference, with no origin request. Resolves to false if none is stored. */
    refreshImage(candidate: FetchCandidate): Promise<boolean>
}
