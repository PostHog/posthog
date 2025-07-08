import { Redis } from 'ioredis'

import { DB } from '~/utils/db/db'
import { PostgresUse } from '~/utils/db/postgres'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'

import { PostIngestionEvent } from '../../types'

export interface BehavioralCohortDefinition {
    id: number
    name: string
    team_id: number
    groups: BehavioralCohortGroup[]
}

export interface BehavioralCohortGroup {
    properties: BehavioralCohortProperty[]
}

export interface BehavioralCohortProperty {
    type: 'behavioral'
    key: string // event name
    value: 'performed_event' | 'performed_event_first_time' | 'performed_event_sequence'
    event_type?: 'events' | 'actions'
    seq_event?: string // for sequence events
    seq_event_type?: string
    operator?: string
    negation?: boolean
}

export interface BehavioralState {
    first_events: Set<string>
    event_sequence: string[]
    last_event_time: number
    last_updated: number
}

export class BehavioralCohortService {
    private redis: Redis
    private db: DB
    private cohortCache: Map<string, BehavioralCohortDefinition> = new Map()
    private stateCache: Map<string, BehavioralState> = new Map()

    constructor(redis: Redis, db: DB) {
        this.redis = redis
        this.db = db
    }

    async evaluateBehavioralCohort(cohortId: number, teamId: number, event: PostIngestionEvent): Promise<boolean> {
        if (!event.person_id) {
            return false
        }

        try {
            // Get cohort definition
            const cohortDef = await this.getCohortDefinition(cohortId, teamId)
            if (!cohortDef) {
                logger.warn(`Behavioral cohort ${cohortId} not found for team ${teamId}`)
                return false
            }

            // Get or create behavioral state for this person
            const state = await this.getBehavioralState(event.person_id, cohortId)

            // Evaluate each group (OR logic between groups)
            for (const group of cohortDef.groups) {
                if (this.evaluateGroup(group, event, state)) {
                    // Update state and return true
                    await this.updateBehavioralState(event.person_id, cohortId, state)
                    return true
                }
            }

            return false
        } catch (error) {
            logger.error(`Error evaluating behavioral cohort ${cohortId}:`, error)
            return false
        }
    }

    private async getCohortDefinition(cohortId: number, teamId: number): Promise<BehavioralCohortDefinition | null> {
        const cacheKey = `${teamId}:${cohortId}`

        // Check cache first
        if (this.cohortCache.has(cacheKey)) {
            return this.cohortCache.get(cacheKey)!
        }

        // Fetch from database
        const cohort = await this.db.postgres.query<BehavioralCohortDefinition, [number, number]>(
            PostgresUse.COMMON_READ,
            `SELECT id, name, team_id, groups FROM posthog_cohort 
             WHERE id = $1 AND team_id = $2 AND deleted = false`,
            [cohortId, teamId],
            'getCohortDefinition'
        )

        if (cohort.rows.length === 0) {
            return null
        }

        const cohortDef: BehavioralCohortDefinition = {
            id: cohort.rows[0].id,
            name: cohort.rows[0].name,
            team_id: cohort.rows[0].team_id,
            groups: cohort.rows[0].groups || [],
        }

        // Cache for 5 minutes
        this.cohortCache.set(cacheKey, cohortDef)
        setTimeout(() => this.cohortCache.delete(cacheKey), 5 * 60 * 1000)

        return cohortDef
    }

    private async getBehavioralState(personId: string, cohortId: number): Promise<BehavioralState> {
        const cacheKey = `${personId}:${cohortId}`

        // Check in-memory cache first
        if (this.stateCache.has(cacheKey)) {
            return this.stateCache.get(cacheKey)!
        }

        // Try Redis
        const redisKey = `behavioral_state:${personId}:${cohortId}`
        const redisData = await this.redis.get(redisKey)

        if (redisData) {
            const parsed = parseJSON(redisData)
            const state: BehavioralState = {
                first_events: new Set(parsed.first_events),
                event_sequence: parsed.event_sequence || [],
                last_event_time: parsed.last_event_time || 0,
                last_updated: parsed.last_updated || Date.now(),
            }

            // Cache in memory for 1 minute
            this.stateCache.set(cacheKey, state)
            setTimeout(() => this.stateCache.delete(cacheKey), 60 * 1000)

            return state
        }

        // Return empty state
        const newState: BehavioralState = {
            first_events: new Set(),
            event_sequence: [],
            last_event_time: 0,
            last_updated: Date.now(),
        }

        this.stateCache.set(cacheKey, newState)
        return newState
    }

    private async updateBehavioralState(personId: string, cohortId: number, state: BehavioralState): Promise<void> {
        const cacheKey = `${personId}:${cohortId}`
        const redisKey = `behavioral_state:${personId}:${cohortId}`

        state.last_updated = Date.now()

        // Update in-memory cache
        this.stateCache.set(cacheKey, state)

        // Update Redis with 1 hour TTL
        const redisData = JSON.stringify({
            first_events: Array.from(state.first_events),
            event_sequence: state.event_sequence,
            last_event_time: state.last_event_time,
            last_updated: state.last_updated,
        })

        await this.redis.setex(redisKey, 3600, redisData)
    }

    private evaluateGroup(group: BehavioralCohortGroup, event: PostIngestionEvent, state: BehavioralState): boolean {
        // AND logic between properties in a group
        for (const property of group.properties) {
            if (property.type !== 'behavioral') {
                continue
            }

            const matches = this.evaluateBehavioralProperty(property, event, state)
            if (!matches) {
                return false
            }
        }
        return true
    }

    private evaluateBehavioralProperty(
        property: BehavioralCohortProperty,
        event: PostIngestionEvent,
        state: BehavioralState
    ): boolean {
        const eventName = event.event
        const targetEvent = property.key

        // Update state with current event
        state.last_event_time = Date.now()

        switch (property.value) {
            case 'performed_event':
                // Check if current event matches
                const matches = eventName === targetEvent
                return property.negation ? !matches : matches

            case 'performed_event_first_time':
                // Check if this is the first time performing this event
                if (eventName === targetEvent) {
                    const isFirstTime = !state.first_events.has(targetEvent)
                    state.first_events.add(targetEvent)
                    return property.negation ? !isFirstTime : isFirstTime
                }
                return property.negation ? true : false

            case 'performed_event_sequence':
                // Track event sequence and check if target sequence is met
                if (eventName === targetEvent) {
                    // Add to sequence (keep last 10 events to limit memory)
                    state.event_sequence.push(eventName)
                    if (state.event_sequence.length > 10) {
                        state.event_sequence.shift()
                    }

                    // Check if sequence condition is met
                    if (property.seq_event) {
                        const hasSequence = this.checkEventSequence(
                            state.event_sequence,
                            targetEvent,
                            property.seq_event
                        )
                        return property.negation ? !hasSequence : hasSequence
                    }
                    return property.negation ? false : true
                }

                // Add non-target events to sequence too
                state.event_sequence.push(eventName)
                if (state.event_sequence.length > 10) {
                    state.event_sequence.shift()
                }

                return property.negation ? true : false

            default:
                logger.warn(`Unsupported behavioral property type: ${property.value}`)
                return false
        }
    }

    private checkEventSequence(sequence: string[], firstEvent: string, secondEvent: string): boolean {
        // Check if firstEvent is followed by secondEvent in the sequence
        for (let i = 0; i < sequence.length - 1; i++) {
            if (sequence[i] === firstEvent && sequence[i + 1] === secondEvent) {
                return true
            }
        }
        return false
    }
}
