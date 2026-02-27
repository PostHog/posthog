import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { PluginsServerConfig } from '~/types'
import { logger } from '~/utils/logger'
import { FetchOptions, FetchResponse, internalFetch } from '~/utils/request'
import { tryCatch } from '~/utils/try-catch'

export class InternalFetchService {
    constructor(private config: Pick<PluginsServerConfig, 'INTERNAL_API_SECRET' | 'INTERNAL_API_BASE_URL'>) {}

    async fetch({
        urlPath,
        fetchParams,
    }: {
        urlPath: `/${string}`
        fetchParams: FetchOptions
    }): Promise<{ fetchError: Error | null; fetchResponse: FetchResponse | null }> {
        logger.debug('Making internal fetch request', { urlPath })

        const internalUrl = `${this.config.INTERNAL_API_BASE_URL || 'http://localhost:8000'}${urlPath}`
        const internalFetchParams = {
            ...fetchParams,
            headers: {
                'Content-Type': 'application/json',
                ...fetchParams.headers,
                ...(this.config.INTERNAL_API_SECRET
                    ? { [INTERNAL_SERVICE_CALL_HEADER_NAME.toLowerCase()]: this.config.INTERNAL_API_SECRET }
                    : {}),
            },
        }

        const [fetchError, fetchResponse] = await tryCatch(
            async () => await internalFetch(internalUrl, internalFetchParams)
        )
        return { fetchError, fetchResponse }
    }
}
