import { Hub, Team } from '~/types'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'

import { HogFunctionFilters } from '../../types'

export interface BlastRadiusResponse {
    users_affected: number
    total_users: number
}

export interface BlastRadiusPersonsResponse {
    users_affected: Array<{
        distinct_id: string
        person_id: string
    }>
    cursor: string | null
    has_more: boolean
}

export interface HogFlowBatchPersonQueryServiceHub {
    SITE_URL: string
    INTERNAL_API_SECRET?: string
}

/**
 * Service for querying persons via Django internal API for batch HogFlow processing.
 * Calls internal endpoints authenticated with INTERNAL_API_SECRET.
 * Endpoints: /internal/hog_flows/user_blast_radius and /internal/hog_flows/user_blast_radius_persons
 */
export class HogFlowBatchPersonQueryService {
    constructor(private hub: Pick<Hub, 'SITE_URL' | 'INTERNAL_API_SECRET' | 'internalFetchService'>) {}

    /**
     * Get count of users affected by filters
     */
    async getBlastRadius(
        team: Team,
        filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>,
        groupTypeIndex?: number
    ): Promise<BlastRadiusResponse> {
        const url = `${this.hub.SITE_URL}/api/projects/${team.id}/internal/hog_flows/user_blast_radius`

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
        }

        // Add internal service token if configured
        if (this.hub.INTERNAL_API_SECRET) {
            headers['Authorization'] = `Bearer ${this.hub.INTERNAL_API_SECRET}`
        }

        try {
            const { fetchResponse, fetchError } = await this.hub.internalFetchService.fetch({
                url,
                fetchParams: {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({
                        filters,
                        group_type_index: groupTypeIndex,
                    }),
                },
            })

            if (!fetchResponse || fetchError) {
                logger.error('Error fetching blast radius from Django', { error: fetchError, url })
                throw fetchError
            }

            if (fetchResponse.status !== 200) {
                const errorText = await fetchResponse.text()
                logger.error('Failed to fetch blast radius from Django', {
                    status: fetchResponse.status,
                    error: errorText,
                    url,
                })
                throw new Error(`Failed to fetch blast radius: ${fetchResponse.status} ${errorText}`)
            }

            const data = parseJSON(await fetchResponse.text()) as BlastRadiusResponse

            return data
        } catch (error) {
            logger.error('Error calling blast radius endpoint', { error, url })
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
        cursor?: string | null
    ): Promise<BlastRadiusPersonsResponse> {
        const url = `${this.hub.SITE_URL}/api/projects/${team.id}/internal/hog_flows/user_blast_radius_persons`

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
        }

        // Add internal service token if configured
        if (this.hub.INTERNAL_API_SECRET) {
            headers['Authorization'] = `Bearer ${this.hub.INTERNAL_API_SECRET}`
        }

        try {
            const { fetchResponse, fetchError } = await this.hub.internalFetchService.fetch({
                url,
                fetchParams: {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({
                        filters,
                        group_type_index: groupTypeIndex,
                        cursor: cursor || null,
                    }),
                },
            })

            if (!fetchResponse || fetchError) {
                logger.error('Error fetching blast radius persons from Django', { error: fetchError, url })
                throw fetchError
            }

            if (fetchResponse.status !== 200) {
                const errorText = await fetchResponse.text()
                logger.error('Failed to fetch blast radius persons from Django', {
                    status: fetchResponse.status,
                    error: errorText,
                    url,
                })
                throw new Error(`Failed to fetch blast radius persons: ${fetchResponse.status} ${errorText}`)
            }

            const data = parseJSON(await fetchResponse.text()) as BlastRadiusPersonsResponse

            return data
        } catch (error) {
            logger.error('Error calling blast radius persons endpoint', { error, url })
            throw error
        }
    }
}
