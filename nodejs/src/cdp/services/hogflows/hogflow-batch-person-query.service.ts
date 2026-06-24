import { InternalFetchService } from '~/common/services/internal-fetch'
import { Team } from '~/types'
import { parseJSON } from '~/utils/json-parse'
import { logger, serializeError } from '~/utils/logger'

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

export interface HogFlowBatchPersonQueryServiceOptions {
    /** Per-call HTTP timeout for blast-radius fetches. Default: 30s. */
    fetchTimeoutMs?: number
    /** Backoff between the initial attempt and the single retry. Default: 500ms. */
    retryBackoffMs?: number
}

// The default external-request budget (3s, EXTERNAL_REQUEST_TIMEOUT_MS) is sized for
// outbound webhooks. Blast-radius fetches hit an internal Django endpoint that runs a
// HogQL → ClickHouse person scan, which routinely takes 1–3s per page. At 100 pages
// for a 50k audience, a 97% per-call success rate collapses to ~5% batch success
// through geometric tail compounding. 30s leaves plenty of headroom; the one retry
// catches occasional spikes without dropping the whole batch.
const DEFAULT_FETCH_TIMEOUT_MS = 30_000
const DEFAULT_RETRY_BACKOFF_MS = 500
const MAX_ATTEMPTS = 2

/**
 * Service for querying persons via Django internal API for batch HogFlow processing.
 * Calls internal endpoints authenticated with INTERNAL_API_SECRET.
 * Endpoints: /internal/hog_flows/user_blast_radius and /internal/hog_flows/user_blast_radius_persons
 */
export class HogFlowBatchPersonQueryService {
    private readonly fetchTimeoutMs: number
    private readonly retryBackoffMs: number

    constructor(
        private internalFetchService: InternalFetchService,
        options: HogFlowBatchPersonQueryServiceOptions = {}
    ) {
        this.fetchTimeoutMs = options.fetchTimeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS
        this.retryBackoffMs = options.retryBackoffMs ?? DEFAULT_RETRY_BACKOFF_MS
    }

    /**
     * POST to an internal endpoint with one retry on timeout / network error / 5xx.
     * 4xx responses are non-retryable (client error) and throw immediately.
     */
    private async fetchInternalEndpoint<T>(urlPath: `/${string}`, body: Record<string, unknown>): Promise<T> {
        let lastError: Error | null = null

        for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            if (attempt > 1) {
                await new Promise<void>((resolve) => setTimeout(resolve, this.retryBackoffMs))
            }

            const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
                urlPath,
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify(body),
                    timeoutMs: this.fetchTimeoutMs,
                },
            })

            if (fetchError) {
                lastError = fetchError
            } else if (!fetchResponse) {
                lastError = new Error('Empty response from internal API')
            } else if (fetchResponse.status === 200) {
                return parseJSON(await fetchResponse.text()) as T
            } else if (fetchResponse.status >= 500) {
                const errorText = await fetchResponse.text()
                lastError = new Error(`HTTP ${fetchResponse.status} from ${urlPath}: ${errorText}`)
            } else {
                // 4xx — client error, not retryable
                const errorText = await fetchResponse.text()
                throw new Error(`HTTP ${fetchResponse.status} from ${urlPath}: ${errorText}`)
            }

            if (attempt < MAX_ATTEMPTS) {
                logger.warn('Retrying internal blast-radius fetch', {
                    urlPath,
                    attempt,
                    error: serializeError(lastError),
                })
            }
        }

        logger.error('Internal blast-radius fetch failed after retries', {
            urlPath,
            attempts: MAX_ATTEMPTS,
            error: serializeError(lastError),
        })
        throw lastError ?? new Error(`Internal blast-radius fetch failed: ${urlPath}`)
    }

    /**
     * Get count of users affected by filters
     */
    async getBlastRadius(
        team: Team,
        filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>,
        groupTypeIndex?: number
    ): Promise<BlastRadiusResponse> {
        const urlPath = `/api/projects/${team.id}/internal/hog_flows/user_blast_radius` as const
        return this.fetchInternalEndpoint<BlastRadiusResponse>(urlPath, {
            filters,
            group_type_index: groupTypeIndex,
        })
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
        cursor?: string | null
    ): Promise<BlastRadiusPersonsResponse> {
        const urlPath = `/api/projects/${team.id}/internal/hog_flows/user_blast_radius_persons` as const
        return this.fetchInternalEndpoint<BlastRadiusPersonsResponse>(urlPath, {
            filters,
            group_type_index: groupTypeIndex,
            cursor: cursor || null,
        })
    }
}
