import { Counter } from 'prom-client'

import { InternalFetchService } from '~/common/services/internal-fetch'
import { parseJSON } from '~/common/utils/json-parse'
import { logger, serializeError } from '~/common/utils/logger'
import { Team } from '~/types'

import { HogFunctionFilters } from '../../types'

export interface BlastRadiusResponse {
    users_affected: number
    total_users: number
}

export interface BlastRadiusPersonsResponse {
    users_affected: Array<string>
    cursor: string | null
    has_more: boolean
}

export interface AccountAudienceResponse {
    accounts: Array<string>
    cursor: string | null
    has_more: boolean
    group_type: string
}

const counterAudienceFetchTimeout = new Counter({
    name: 'cdp_batch_hog_flow_audience_fetch_timeout',
    help: 'An audience fetch for a batch hog flow exceeded its client-side timeout budget',
    labelNames: ['endpoint'],
})

export type AudienceFetchEndpoint = 'user_blast_radius' | 'user_blast_radius_persons' | 'account_audience'

/**
 * An audience fetch used its full CDP_HOG_FLOW_BATCH_AUDIENCE_FETCH_TIMEOUT_MS budget.
 * The client aborted the request. The query behind the endpoint keeps running server-side
 * until the HogQL execution cap, so a timeout means the query is too slow, and not that
 * Django is unreachable. The two failures need different operator action, so they get
 * different error types.
 */
export class AudienceFetchTimeoutError extends Error {
    override name = 'AudienceFetchTimeoutError'

    constructor(
        public readonly endpoint: AudienceFetchEndpoint,
        public readonly timeoutMs: number
    ) {
        super(
            `Audience fetch to ${endpoint} timed out after ${timeoutMs}ms. The audience query did not finish ` +
                `inside CDP_HOG_FLOW_BATCH_AUDIENCE_FETCH_TIMEOUT_MS.`
        )
    }
}

// AbortSignal.timeout rejects with a TimeoutError. undici reports some aborts as an
// AbortError, and can wrap either one in `cause`.
const TIMEOUT_ERROR_NAMES = ['TimeoutError', 'AbortError']

const isTimeoutError = (error: unknown): boolean => {
    const name = (error as { name?: string } | null)?.name
    const causeName = (error as { cause?: { name?: string } } | null)?.cause?.name
    return TIMEOUT_ERROR_NAMES.includes(name ?? '') || TIMEOUT_ERROR_NAMES.includes(causeName ?? '')
}

/**
 * Service for querying persons via Django internal API for batch HogFlow processing.
 * Calls internal endpoints authenticated with INTERNAL_API_SECRET.
 * Endpoints: /internal/hog_flows/user_blast_radius and /internal/hog_flows/user_blast_radius_persons
 */
export class HogFlowBatchPersonQueryService {
    constructor(
        private internalFetchService: InternalFetchService,
        private audienceFetchTimeoutMs: number
    ) {}

    /**
     * Raise the error the caller sees for a transport failure. A timeout gets its own error
     * type and its own counter, because the audience query is too slow for the budget. Any
     * other transport error keeps its original type.
     */
    private failFetch(endpoint: AudienceFetchEndpoint, urlPath: string, fetchError: Error | null): never {
        if (isTimeoutError(fetchError)) {
            counterAudienceFetchTimeout.labels({ endpoint }).inc()
            logger.error('Audience fetch timed out', {
                endpoint,
                urlPath,
                timeoutMs: this.audienceFetchTimeoutMs,
                error: serializeError(fetchError),
            })
            throw new AudienceFetchTimeoutError(endpoint, this.audienceFetchTimeoutMs)
        }

        logger.error('Error fetching audience from Django', {
            endpoint,
            urlPath,
            error: serializeError(fetchError),
        })
        throw fetchError ?? new Error(`Audience fetch to ${endpoint} returned no response`)
    }

    /**
     * Get count of users affected by filters
     */
    async getBlastRadius(
        team: Team,
        filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>,
        groupTypeIndex?: number
    ): Promise<BlastRadiusResponse> {
        // The /internal endpoints aren't exposed publicly and require INTERNAL_API_SECRET for authentication
        const urlPath = `/api/projects/${team.id}/internal/hog_flows/user_blast_radius` as const

        try {
            const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
                urlPath,
                fetchParams: {
                    method: 'POST',
                    timeoutMs: this.audienceFetchTimeoutMs,
                    body: JSON.stringify({
                        filters,
                        group_type_index: groupTypeIndex,
                    }),
                },
            })

            if (!fetchResponse || fetchError) {
                this.failFetch('user_blast_radius', urlPath, fetchError)
            }

            if (fetchResponse.status !== 200) {
                const errorText = await fetchResponse.text()
                logger.error('Failed to fetch blast radius from Django', {
                    status: fetchResponse.status,
                    error: errorText,
                    urlPath,
                })
                throw new Error(`Failed to fetch blast radius: ${fetchResponse.status} ${errorText}`)
            }

            const data = parseJSON(await fetchResponse.text()) as BlastRadiusResponse

            return data
        } catch (error) {
            logger.error('Error calling blast radius endpoint', { error: serializeError(error), urlPath })
            throw error
        }
    }

    /**
     * Get list of persons affected by filters with cursor-based pagination.
     * Returns distinct_id and person_id for each matching person, plus pagination info.
     *
     * @param cursor - Optional cursor from previous response for pagination
     */
    async getBlastRadiusPersons(
        team: Team,
        filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>,
        groupTypeIndex?: number,
        cursor?: string | null,
        dedupeKey?: 'email'
    ): Promise<BlastRadiusPersonsResponse> {
        const urlPath = `/api/projects/${team.id}/internal/hog_flows/user_blast_radius_persons` as const

        try {
            const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
                urlPath,
                fetchParams: {
                    method: 'POST',
                    timeoutMs: this.audienceFetchTimeoutMs,
                    body: JSON.stringify({
                        filters,
                        group_type_index: groupTypeIndex,
                        cursor: cursor || null,
                        dedupe_key: dedupeKey ?? null,
                    }),
                },
            })

            if (!fetchResponse || fetchError) {
                this.failFetch('user_blast_radius_persons', urlPath, fetchError)
            }

            if (fetchResponse.status !== 200) {
                const errorText = await fetchResponse.text()
                logger.error('Failed to fetch blast radius persons from Django', {
                    status: fetchResponse.status,
                    error: errorText,
                    urlPath,
                })
                throw new Error(`Failed to fetch blast radius persons: ${fetchResponse.status} ${errorText}`)
            }

            const data = parseJSON(await fetchResponse.text()) as BlastRadiusPersonsResponse

            return data
        } catch (error) {
            logger.error('Error calling blast radius persons endpoint', { error: serializeError(error), urlPath })
            throw error
        }
    }

    /**
     * Page a customer analytics account audience (external ids), cursor-paginated.
     */
    async getAccountAudiencePage(
        team: Team,
        filters: unknown,
        cursor?: string | null
    ): Promise<AccountAudienceResponse> {
        const urlPath = `/api/projects/${team.id}/internal/hog_flows/account_audience` as const

        try {
            const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
                urlPath,
                fetchParams: {
                    method: 'POST',
                    timeoutMs: this.audienceFetchTimeoutMs,
                    body: JSON.stringify({
                        filters,
                        cursor: cursor || null,
                    }),
                },
            })

            if (!fetchResponse || fetchError) {
                this.failFetch('account_audience', urlPath, fetchError)
            }

            if (fetchResponse.status !== 200) {
                const errorText = await fetchResponse.text()
                logger.error('Failed to fetch account audience from Django', {
                    status: fetchResponse.status,
                    error: errorText,
                    urlPath,
                })
                throw new Error(`Failed to fetch account audience: ${fetchResponse.status} ${errorText}`)
            }

            const data = parseJSON(await fetchResponse.text()) as AccountAudienceResponse

            return data
        } catch (error) {
            logger.error('Error calling account audience endpoint', { error: serializeError(error), urlPath })
            throw error
        }
    }
}
