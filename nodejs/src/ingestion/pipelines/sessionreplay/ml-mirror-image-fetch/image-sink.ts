import type { FetchCandidate } from './collected-urls-record'
import type { ImageFetchResult } from './image-fetcher'

/**
 * Where a fetched image goes. The lane hands every image it fetched to one sink, and the image counts as handled only
 * once the sink resolves: a rejection keeps the URL unfinished, so it is fetched again.
 */
export interface FetchedImageSink {
    publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<void>
}
