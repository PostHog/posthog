import { Counter, Histogram } from 'prom-client'

import { InternalFetchService } from '~/common/services/internal-fetch'
import { parseJSON } from '~/common/utils/json-parse'
import { logger, serializeError } from '~/common/utils/logger'
import { Team } from '~/types'

import { HogFunctionFilters } from '../../types'
import { ScopedServiceJwt } from '../../utils/scoped-service-jwt'

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

export interface RecipientListRecipient {
    email: string
    person_id: string | null
    distinct_id: string | null
    variables: Record<string, string>
}

export interface RecipientListPageResponse {
    recipients: Array<RecipientListRecipient>
    cursor: string | null
    has_more: boolean
}

const counterAudienceFetchTimeout = new Counter({
    name: 'cdp_batch_hog_flow_audience_fetch_timeout',
    help: 'An audience fetch for a batch hog flow exceeded its client-side timeout budget',
    labelNames: ['endpoint'],
})

// Bucket edges sit around the fetch budget; instrumented_function_duration_seconds jumps from 25.6s to 102.4s.
const histogramAudienceFetchDuration = new Histogram({
    name: 'cdp_batch_hog_flow_audience_fetch_duration_seconds',
    help: 'Wall time of one audience fetch for a batch hog flow, from request to response body read',
    labelNames: ['endpoint', 'outcome'], // success | timeout | error
    buckets: [1, 2, 5, 10, 20, 30, 40, 50, 60, 90, 120],
})

export type AudienceFetchEndpoint =
    | 'user_blast_radius'
    | 'user_blast_radius_persons'
    | 'account_audience'
    | 'recipient_list_page'

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
        private audienceFetchTimeoutMs: number,
        // The recipient list endpoint takes a scoped JWT, so its fetch service carries no INTERNAL_API_SECRET.
        private recipientLists?: { fetchService: InternalFetchService; jwt: ScopedServiceJwt }
    ) {}

    /**
     * Raise the error the caller sees for a transport failure. A timeout gets its own error
     * type and its own counter, because the audience query is too slow for the budget. Any
     * other transport error keeps its original type.
     */
    private failFetch(
        endpoint: AudienceFetchEndpoint,
        urlPath: string,
        fetchError: Error | null,
        durationMs: number
    ): never {
        if (isTimeoutError(fetchError)) {
            counterAudienceFetchTimeout.labels({ endpoint }).inc()
            histogramAudienceFetchDuration.labels({ endpoint, outcome: 'timeout' }).observe(durationMs / 1000)
            logger.error('Audience fetch timed out', {
                endpoint,
                urlPath,
                durationMs,
                timeoutMs: this.audienceFetchTimeoutMs,
                error: serializeError(fetchError),
            })
            throw new AudienceFetchTimeoutError(endpoint, this.audienceFetchTimeoutMs)
        }

        histogramAudienceFetchDuration.labels({ endpoint, outcome: 'error' }).observe(durationMs / 1000)
        logger.error('Error fetching audience from Django', {
            endpoint,
            urlPath,
            durationMs,
            error: serializeError(fetchError),
        })
        throw fetchError ?? new Error(`Audience fetch to ${endpoint} returned no response`)
    }

    private async fetchAudience<T>(
        endpoint: AudienceFetchEndpoint,
        urlPath: `/${string}`,
        body: Record<string, unknown>,
        failureLabel: string,
        fetchService: InternalFetchService = this.internalFetchService,
        headers?: Record<string, string>
    ): Promise<T> {
        const startedAt = performance.now()
        const { fetchResponse, fetchError } = await fetchService.fetch({
            urlPath,
            fetchParams: {
                method: 'POST',
                timeoutMs: this.audienceFetchTimeoutMs,
                body: JSON.stringify(body),
                headers,
            },
        })
        const elapsedMs = (): number => Math.round(performance.now() - startedAt)

        if (!fetchResponse || fetchError) {
            this.failFetch(endpoint, urlPath, fetchError, elapsedMs())
        }

        const text = await fetchResponse.text()
        const durationMs = elapsedMs()

        if (fetchResponse.status !== 200) {
            histogramAudienceFetchDuration.labels({ endpoint, outcome: 'error' }).observe(durationMs / 1000)
            logger.error(`Failed to fetch ${failureLabel} from Django`, {
                status: fetchResponse.status,
                error: text,
                urlPath,
                durationMs,
            })
            throw new Error(`Failed to fetch ${failureLabel}: ${fetchResponse.status} ${text}`)
        }

        histogramAudienceFetchDuration.labels({ endpoint, outcome: 'success' }).observe(durationMs / 1000)
        if (durationMs * 2 > this.audienceFetchTimeoutMs) {
            // The histogram has no team label; the urlPath here does.
            logger.warn('Slow audience fetch', {
                endpoint,
                urlPath,
                durationMs,
                timeoutMs: this.audienceFetchTimeoutMs,
            })
        }
        return parseJSON(text) as T
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
            return await this.fetchAudience<BlastRadiusResponse>(
                'user_blast_radius',
                urlPath,
                { filters, group_type_index: groupTypeIndex },
                'blast radius'
            )
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
            return await this.fetchAudience<BlastRadiusPersonsResponse>(
                'user_blast_radius_persons',
                urlPath,
                {
                    filters,
                    group_type_index: groupTypeIndex,
                    cursor: cursor || null,
                    dedupe_key: dedupeKey ?? null,
                },
                'blast radius persons'
            )
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
            return await this.fetchAudience<AccountAudienceResponse>(
                'account_audience',
                urlPath,
                { filters, cursor: cursor || null },
                'account audience'
            )
        } catch (error) {
            logger.error('Error calling account audience endpoint', { error: serializeError(error), urlPath })
            throw error
        }
    }

    /**
     * Page an uploaded recipient list. Each recipient arrives matched to a person where one exists.
     */
    async getRecipientListPage(
        team: Team,
        recipientListId: string,
        cursor?: string | null
    ): Promise<RecipientListPageResponse> {
        if (!this.recipientLists?.jwt.enabled) {
            throw new Error(
                'Recipient list audiences are not configured in this environment (WORKFLOW_RECIPIENT_LIST_JWT_SECRET unset)'
            )
        }
        const urlPath = `/api/projects/${team.id}/workflow_recipient_list_pages/` as const
        // The token names the list, so Django never trusts a list id from the request body.
        const token = this.recipientLists.jwt.mint({ team_id: team.id, recipient_list_id: recipientListId })

        try {
            return await this.fetchAudience<RecipientListPageResponse>(
                'recipient_list_page',
                urlPath,
                { cursor: cursor || null },
                'recipient list page',
                this.recipientLists.fetchService,
                { Authorization: `Bearer ${token}` }
            )
        } catch (error) {
            logger.error('Error calling recipient list page endpoint', { error: serializeError(error), urlPath })
            throw error
        }
    }
}
