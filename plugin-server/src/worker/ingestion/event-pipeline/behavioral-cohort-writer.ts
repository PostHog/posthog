import { PluginEvent } from '@posthog/plugin-scaffold'
import { promises as fs } from 'fs'

import { Team } from '../../../types'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'

interface BehavioralFilter {
    key: string
    type: string
    value: string
    operator: string
    operator_value: number
    explicit_datetime: string
    negation: boolean
}

interface BehavioralCohort {
    id: number
    name: string
    behavioralFilters: BehavioralFilter[]
}

const behavioralCohortsCache: Map<number, BehavioralCohort[]> = new Map()
const cacheTimestamp: Map<number, number> = new Map()
const CACHE_TTL = 60 * 1000 // 1 minute

export async function behavioralCohortWriterStep(
    event: PluginEvent,
    team: Team,
    postgres: PostgresRouter
): Promise<PluginEvent> {
    try {
        const behavioralCohorts = await getBehavioralCohortsForTeam(team.id, postgres)

        for (const cohort of behavioralCohorts) {
            if (eventMatchesBehavioralCohort(event, cohort)) {
                await writeEventMatch(event, cohort, team)
            }
        }
    } catch (error) {
        console.error('Error in behavioral cohort writer step:', error)
        // Don't fail the pipeline if this step fails
    }

    return event // Pass through unchanged
}

function eventMatchesBehavioralCohort(event: PluginEvent, cohort: BehavioralCohort): boolean {
    // Check if the event matches any of the behavioral filters
    for (const filter of cohort.behavioralFilters) {
        if (filter.key === event.event && filter.type === 'behavioral') {
            return true
        }
    }
    return false
}

async function writeEventMatch(event: PluginEvent, cohort: BehavioralCohort, team: Team): Promise<void> {
    const logEntry = {
        timestamp: new Date().toISOString(),
        team_id: event.team_id,
        team_name: team.name,
        cohort_id: cohort.id,
        cohort_name: cohort.name,
        event_name: event.event,
        distinct_id: event.distinct_id,
        properties: event.properties,
        uuid: event.uuid,
    }

    const logDir = '/tmp/posthog-behavioral-cohorts'
    const logFile = `${logDir}/behavioral-cohort-matches.jsonl`

    try {
        // Ensure directory exists
        await fs.mkdir(logDir, { recursive: true })

        // Append to file
        await fs.appendFile(logFile, JSON.stringify(logEntry) + '\n')

        console.log(`Behavioral cohort match: ${event.event} -> cohort ${cohort.id} (${cohort.name})`)
    } catch (error) {
        console.error('Error writing behavioral cohort match:', error)
    }
}

async function getBehavioralCohortsForTeam(teamId: number, postgres: PostgresRouter): Promise<BehavioralCohort[]> {
    const now = Date.now()

    // Check cache
    if (behavioralCohortsCache.has(teamId)) {
        const cacheTime = cacheTimestamp.get(teamId) || 0
        if (now - cacheTime < CACHE_TTL) {
            return behavioralCohortsCache.get(teamId)!
        }
    }

    try {
        const result = await postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT id, name, properties 
             FROM posthog_cohort 
             WHERE team_id = $1 
             AND properties::text LIKE '%behavioral%'
             AND deleted = false`,
            [teamId],
            'getBehavioralCohortsForTeam'
        )

        const cohorts: BehavioralCohort[] = []

        for (const row of result.rows) {
            const behavioralFilters = extractBehavioralFilters(row.properties)
            if (behavioralFilters.length > 0) {
                cohorts.push({
                    id: row.id,
                    name: row.name,
                    behavioralFilters,
                })
            }
        }

        // Update cache
        behavioralCohortsCache.set(teamId, cohorts)
        cacheTimestamp.set(teamId, now)

        return cohorts
    } catch (error) {
        console.error('Error loading behavioral cohorts:', error)
        return []
    }
}

function extractBehavioralFilters(properties: any): BehavioralFilter[] {
    const filters: BehavioralFilter[] = []

    if (!properties || !properties.values) {
        return filters
    }

    // Navigate the nested structure
    for (const topLevelValue of properties.values) {
        if (topLevelValue.type === 'OR' && topLevelValue.values) {
            for (const orValue of topLevelValue.values) {
                if (orValue.type === 'OR' && orValue.values) {
                    for (const filter of orValue.values) {
                        if (filter.type === 'behavioral') {
                            filters.push({
                                key: filter.key,
                                type: filter.type,
                                value: filter.value,
                                operator: filter.operator,
                                operator_value: filter.operator_value,
                                explicit_datetime: filter.explicit_datetime,
                                negation: filter.negation || false,
                            })
                        }
                    }
                }
            }
        }
    }

    return filters
}
