import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { logger } from '~/utils/logger'
import { FetchOptions, FetchResponse, internalFetch } from '~/utils/request'
import { tryCatch } from '~/utils/try-catch'

export class InternalFetchService {
    constructor(
        private internalApiBaseUrl: string,
        private internalApiSecret: string
    ) {}

    async fetch({
        urlPath,
        fetchParams,
    }: {
        urlPath: `/${string}`
        fetchParams: FetchOptions
    }): Promise<{ fetchError: Error | null; fetchResponse: FetchResponse | null }> {
        logger.debug('Making internal fetch request', { urlPath })

        const internalUrl = `${this.internalApiBaseUrl || 'http://localhost:8000'}${urlPath}`
        const internalFetchParams = {
            ...fetchParams,
            headers: {
                'Content-Type': 'application/json',
                ...fetchParams.headers,
                ...(this.internalApiSecret
                    ? { [INTERNAL_SERVICE_CALL_HEADER_NAME.toLowerCase()]: this.internalApiSecret }
                    : {}),
            },
        }

        const [fetchError, fetchResponse] = await tryCatch(
            async () => await internalFetch(internalUrl, internalFetchParams)
        )
        return { fetchError, fetchResponse }
    }
}
