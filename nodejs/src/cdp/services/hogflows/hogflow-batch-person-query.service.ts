import { Team } from '~/types'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'
import { fetch } from '~/utils/request'

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
    POSTHOG_INTERNAL_SERVICE_TOKEN: string | null
}

/**
 * Service for querying persons via Django internal API for batch HogFlow processing.
 * Calls internal endpoints authenticated with POSTHOG_INTERNAL_SERVICE_TOKEN.
 * Endpoints: /internal/hog_flows/user_blast_radius and /internal/hog_flows/user_blast_radius_persons
 */
export class HogFlowBatchPersonQueryService {
    constructor(private hub: HogFlowBatchPersonQueryServiceHub) {}

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
        if (this.hub.POSTHOG_INTERNAL_SERVICE_TOKEN) {
            headers['Authorization'] = `Bearer ${this.hub.POSTHOG_INTERNAL_SERVICE_TOKEN}`
        }

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    filters,
                    group_type_index: groupTypeIndex,
                }),
            })

            if (response.status !== 200) {
                const errorText = await response.text()
                logger.error('Failed to fetch blast radius from Django', {
                    status: response.status,
                    error: errorText,
                    url,
                })
                throw new Error(`Failed to fetch blast radius: ${response.status} ${response.statusText}`)
            }

            const data = parseJSON(await response.text()) as BlastRadiusResponse

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
        if (this.hub.POSTHOG_INTERNAL_SERVICE_TOKEN) {
            headers['Authorization'] = `Bearer ${this.hub.POSTHOG_INTERNAL_SERVICE_TOKEN}`
        }

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    filters,
                    group_type_index: groupTypeIndex,
                    cursor: cursor || null,
                }),
            })

            if (response.status !== 200) {
                const errorText = await response.text()
                logger.error('Failed to fetch blast radius persons from Django', {
                    status: response.status,
                    error: errorText,
                    url,
                })
                throw new Error(`Failed to fetch blast radius persons: ${response.status} ${response.statusText}`)
            }

            const data = parseJSON(await response.text()) as BlastRadiusPersonsResponse

            return data
        } catch (error) {
            logger.error('Error calling blast radius persons endpoint', { error, url })
            throw error
        }
    }
}
