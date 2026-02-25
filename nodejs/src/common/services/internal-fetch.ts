import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { cdpTrackedFetch } from '~/cdp/services/hog-executor.service'
import { PluginsServerConfig } from '~/types'
import { logger } from '~/utils/logger'
import { FetchOptions, FetchResponse } from '~/utils/request'

export class InternalFetchService {
    constructor(private config: Pick<PluginsServerConfig, 'INTERNAL_API_SECRET' | 'INTERNAL_API_BASE_URL'>) {}

    async fetch({
        urlPath,
        fetchParams,
    }: {
        urlPath: `/${string}`
        fetchParams: FetchOptions
    }): Promise<{ fetchError: Error | null; fetchResponse: FetchResponse | null; fetchDuration: number }> {
        logger.debug('Making internal fetch request', { urlPath })

        const internalUrl = `${this.config.INTERNAL_API_BASE_URL || 'http://localhost:8000'}${urlPath}`

        return await cdpTrackedFetch({
            url: internalUrl,
            fetchParams: {
                ...fetchParams,
                headers: {
                    'Content-Type': 'application/json',
                    ...fetchParams.headers,
                    ...(this.config.INTERNAL_API_SECRET
                        ? { [INTERNAL_SERVICE_CALL_HEADER_NAME.toLowerCase()]: this.config.INTERNAL_API_SECRET }
                        : {}),
                },
            },
            templateId: 'InternalFetchService',
        })
    }
}
