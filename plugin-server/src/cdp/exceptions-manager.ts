import LRUCache from 'lru-cache'

import { Hub, Team } from '../types'
import { PostgresUse } from '../utils/db/postgres'
import { HogFunctionInvocationGlobals } from './types'

// Maps a fingerprintfor easy lookup like: { 'team_id:merged_fingerprint': primary_fingerprint }
type ExceptionFingerprintByTeamType = Record<string, string>

type ExceptionGroup = {
    mergedFingerprints: string[][]
    active: boolean
}

const FINGERPRINT_CACHE_AGE_MS = 60 * 10 * 1000 // 10 minutes

export class ExceptionsManager {
    fingerprintMappingCache: LRUCache<number, Record<string, ExceptionGroup>> // team_id: { primary_fingerprint: ExceptionGroup }

    constructor(private hub: Hub) {
        // There is only 5 per team so we can have a very high cache and a very long cooldown
        this.fingerprintMappingCache = new LRUCache({ max: 1_000_000, maxAge: FINGERPRINT_CACHE_AGE_MS })
    }

    private async fetchExceptionFingerprintMapping(teams: Team['id'][]): Promise<ExceptionFingerprintByTeamType> {
        const exceptionFingerprintMapping: ExceptionFingerprintByTeamType = {}

        // Load the cached values so we definitely have them
        teams.forEach((teamId) => {
            const cached = this.fingerprintMappingCache.get(teamId)

            if (cached) {
                Object.entries(cached).forEach(([primaryFingerprint, { mergedFingerprints }]) => {
                    mergedFingerprints.forEach((mergedFingerprint) => {
                        exceptionFingerprintMapping[`${teamId}:${mergedFingerprint}`] = primaryFingerprint
                    })
                })
            }
        })

        const teamsToLoad = teams.filter((teamId) => !this.fingerprintMappingCache.get(teamId))

        if (teamsToLoad.length) {
            const result = await this.hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT fingerprint, merged_fingerprints, team_id, status
                FROM posthog_errortrackinggroup
                WHERE team_id = ANY($1) AND merged_fingerprints != '{}'`,
                [teamsToLoad],
                'fetchExceptionTrackingGroups'
            )

            const groupedByTeam: Record<number, Record<string, ExceptionGroup>> = result.rows.reduce((acc, row) => {
                if (!acc[row.team_id]) {
                    acc[row.team_id] = {}
                }
                const stringifiedFingerprint = encodeURIComponent(row.fingerprint.join(','))
                acc[row.team_id][stringifiedFingerprint] = {
                    mergedFingerprints: row.merged_fingerprints,
                    active: acc.status === 'active',
                }
                return acc
            }, {})

            // Save to cache
            Object.entries(groupedByTeam).forEach(([teamId, exceptionTrackingGroups]) => {
                this.fingerprintMappingCache.set(parseInt(teamId), exceptionTrackingGroups)
                Object.entries(exceptionTrackingGroups).forEach(([primaryFingerprint, { mergedFingerprints }]) => {
                    mergedFingerprints.forEach((mergedFingerprint) => {
                        exceptionFingerprintMapping[`${teamId}:${mergedFingerprint}`] = primaryFingerprint
                    })
                })
            })
        }

        return exceptionFingerprintMapping
    }

    public isActive(item: HogFunctionInvocationGlobals): boolean {
        const fingerprint = item.event.properties['$exception_fingerprint'].join(',')
        const groupsForTeam = this.fingerprintMappingCache.get(item.project.id)
        return groupsForTeam && groupsForTeam[fingerprint] ? groupsForTeam[fingerprint].active : false
    }

    /**
     * This function looks complex but is trying to be as optimized as possible.
     *
     * It replaces the fingerprint of exception event items with the primary fingerprint
     * so that masking can be correctly applied to merged fingerprints.
     */
    public async enrichExceptions(items: HogFunctionInvocationGlobals[]): Promise<HogFunctionInvocationGlobals[]> {
        const exceptionEventItems = items.filter((x) => x.event.name === '$exception')
        const byTeamType = await this.fetchExceptionFingerprintMapping(
            Array.from(new Set(exceptionEventItems.map((global) => global.project.id)))
        )

        exceptionEventItems.forEach((item) => {
            const fingerprint: string[] = item.event.properties['$exception_fingerprint']

            if (fingerprint) {
                const team_id = item.project.id
                const primaryFingerprint = byTeamType[`${team_id}:${encodeURIComponent(fingerprint.join(','))}`]

                if (primaryFingerprint) {
                    item.event.properties['$exception_fingerprint'] = primaryFingerprint
                }
            }
        })

        return items
    }
}
