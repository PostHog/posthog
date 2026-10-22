import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'

import { CohortMembershipRepository, StoredCohortRow } from '../cohorts/cohort-membership-repository'

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export type CohortMembershipKey = { teamId: number; personId: string | null | undefined }

export type CohortMembershipChangeOverlay = {
    teamId: number
    personId: string
    cohortId: number
    inCohort: boolean
    // The change's version stamp, in milliseconds since the epoch.
    changedAt: number
}

// A malformed id would fail the whole team's query on the uuid cast, so it reads as no person.
function normalizedPersonId(personId: string | null | undefined): string | null {
    return personId && UUID_REGEX.test(personId) ? personId.toLowerCase() : null
}

// One retry covers a connection that was slow to open. A longer outage falls back to the next event.
const LOAD_ATTEMPTS = 2

async function withRetry<T>(teamId: number, load: () => Promise<T>): Promise<T | null> {
    for (let attempt = 1; attempt <= LOAD_ATTEMPTS; attempt++) {
        try {
            return await load()
        } catch (error) {
            logger.warn('⚠️', 'Cohort membership lookup failed in the subscription matcher', {
                teamId,
                attempt,
                error: String(error),
            })
        }
    }
    return null
}

/**
 * The cohort membership of the people in one subscription matcher batch. load() runs one query per
 * team for the people it has not loaded yet, so every check in the batch reads from memory.
 */
export class BatchCohortMembership {
    private memberCohortIds = new Map<number, Map<string, number[]>>()
    private failedTeams = new Set<number>()

    constructor(private repository: CohortMembershipRepository) {}

    async load(people: CohortMembershipKey[]): Promise<void> {
        const missingByTeam = new Map<number, Set<string>>()
        for (const { teamId, personId } of people) {
            const id = normalizedPersonId(personId)
            if (!id || this.failedTeams.has(teamId) || this.memberCohortIds.get(teamId)?.has(id)) {
                continue
            }
            const missing = missingByTeam.get(teamId) ?? new Set<string>()
            missing.add(id)
            missingByTeam.set(teamId, missing)
        }

        await Promise.all(
            [...missingByTeam].map(async ([teamId, personIds]) => {
                const loaded = await withRetry(teamId, () =>
                    this.repository.getMemberCohortIdsForPersons(teamId, [...personIds])
                )
                if (!loaded) {
                    this.failedTeams.add(teamId)
                    return
                }
                const team = this.memberCohortIds.get(teamId) ?? new Map<string, number[]>()
                for (const [personId, cohortIds] of loaded) {
                    team.set(personId, cohortIds)
                }
                this.memberCohortIds.set(teamId, team)
            })
        )
    }

    /**
     * The person's member cohort ids, or null when they are unknown because the lookup failed or never
     * ran. A person-less event is a non-member of every cohort, as it is for a conditional_branch.
     */
    cohortIdsFor(teamId: number, personId: string | null | undefined): number[] | null {
        const id = normalizedPersonId(personId)
        if (!id) {
            return []
        }
        return this.memberCohortIds.get(teamId)?.get(id) ?? null
    }
}

type CohortState = StoredCohortRow

// A state replaces another only when it is at least as new. A state without a version stamp is the oldest.
function isNewer(next: CohortState, current: CohortState | undefined): boolean {
    return !current || current.version === null || (next.version !== null && next.version >= current.version)
}

function changeState(change: CohortMembershipChangeOverlay): CohortState {
    return { inCohort: change.inCohort, version: change.changedAt }
}

const RECENT_CHANGES_MAX_PEOPLE = 100_000
const RECENT_CHANGES_TTL_MS = 60 * 60 * 1000

/**
 * The newest membership change the matcher has seen for each person and cohort. The membership writer
 * reads the topic in its own consumer group, so the table can miss a change from an earlier batch. The
 * topic is keyed by person, so one matcher pod sees all of a person's changes until a rebalance.
 */
export class RecentCohortMembershipChanges {
    private changes = new LRUCache<string, Map<number, CohortState>>({
        max: RECENT_CHANGES_MAX_PEOPLE,
        ttl: RECENT_CHANGES_TTL_MS,
    })

    record(change: CohortMembershipChangeOverlay): void {
        const key = `${change.teamId}:${change.personId.toLowerCase()}`
        const person = this.changes.get(key) ?? new Map<number, CohortState>()
        const next = changeState(change)
        if (isNewer(next, person.get(change.cohortId))) {
            person.set(change.cohortId, next)
        }
        this.changes.set(key, person)
    }

    get(teamId: number, personId: string): Map<number, CohortState> | undefined {
        return this.changes.get(`${teamId}:${personId.toLowerCase()}`)
    }
}

/**
 * The stored rows of the goal cohorts for the people in one batch of membership changes, with the
 * version stamps a change is compared against.
 */
export class BatchCohortGoalMembership {
    private rows = new Map<number, Map<string, Map<number, CohortState>>>()

    constructor(private repository: CohortMembershipRepository) {}

    async load(people: { teamId: number; personId: string; cohortIds: number[] }[]): Promise<void> {
        const byTeam = new Map<number, { personIds: Set<string>; cohortIds: Set<number> }>()
        for (const { teamId, personId, cohortIds } of people) {
            const id = normalizedPersonId(personId)
            if (!id) {
                continue
            }
            const team = byTeam.get(teamId) ?? { personIds: new Set<string>(), cohortIds: new Set<number>() }
            team.personIds.add(id)
            cohortIds.forEach((cohortId) => team.cohortIds.add(cohortId))
            byTeam.set(teamId, team)
        }

        await Promise.all(
            [...byTeam].map(async ([teamId, { personIds, cohortIds }]) => {
                const loaded = await withRetry(teamId, () =>
                    this.repository.getCohortMembershipsForPersons(teamId, [...personIds], [...cohortIds])
                )
                if (!loaded) {
                    return
                }
                this.rows.set(
                    teamId,
                    new Map([...personIds].map((id) => [id, loaded.get(id) ?? new Map<number, CohortState>()]))
                )
            })
        )
    }

    /**
     * A replay of the person's goal cohort states. Each state is the newest of the stored row, a recent
     * change, and the changes applied so far, so a change never overwrites a row the writer stored from a
     * newer one. Without loaded rows, only the changes are known.
     */
    replay(
        teamId: number,
        personId: string,
        goalCohortIds: number[],
        recent: Map<number, CohortState> | undefined
    ): CohortGoalReplay {
        const id = normalizedPersonId(personId)
        const stored = id ? this.rows.get(teamId)?.get(id) : undefined
        const states = new Map<number, CohortState>()
        for (const cohortId of goalCohortIds) {
            // Once the rows are loaded, a cohort without a row is one the person is not in.
            const base = stored ? (stored.get(cohortId) ?? { inCohort: false, version: null }) : undefined
            const cached = recent?.get(cohortId)
            const state = cached && isNewer(cached, base) ? cached : base
            if (state) {
                states.set(cohortId, state)
            }
        }
        return new CohortGoalReplay(goalCohortIds, states)
    }
}

export class CohortGoalReplay {
    constructor(
        private goalCohortIds: number[],
        private states: Map<number, CohortState>
    ) {}

    apply(change: CohortMembershipChangeOverlay): void {
        const next = changeState(change)
        if (this.goalCohortIds.includes(change.cohortId) && isNewer(next, this.states.get(change.cohortId))) {
            this.states.set(change.cohortId, next)
        }
    }

    /**
     * The goal cohorts the person is in at the moment of a change, or null while the state of one of
     * them is unknown. The changed cohort takes the change's state even when a newer state is known,
     * because the person was in that state when the change happened.
     */
    memberCohortIdsAt(change: CohortMembershipChangeOverlay): number[] | null {
        const states = new Map(this.states).set(change.cohortId, changeState(change))
        if (this.goalCohortIds.some((cohortId) => !states.has(cohortId))) {
            return null
        }
        return this.goalCohortIds.filter((cohortId) => states.get(cohortId)?.inCohort)
    }
}
