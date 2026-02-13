import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { cdpTrackedFetch } from '~/cdp/services/hog-executor.service'
import { PluginsServerConfig } from '~/types'
import { logger } from '~/utils/logger'
import { FetchOptions, FetchResponse } from '~/utils/request'

export class InternalFetchService {
    constructor(private config: Pick<PluginsServerConfig, 'INTERNAL_API_SECRET'>) {}

    async fetch({
        url,
        fetchParams,
    }: {
        url: string
        fetchParams: FetchOptions
    }): Promise<{ fetchError: Error | null; fetchResponse: FetchResponse | null; fetchDuration: number }> {
        logger.debug('Making internal fetch request', { url })
        return await cdpTrackedFetch({
            url,
            fetchParams: {
                ...fetchParams,
                headers: {
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
