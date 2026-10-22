import { logger } from '~/common/utils/logger'

import { CohortMembershipRepository } from '../cohorts/cohort-membership-repository'

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export type CohortMembershipKey = { teamId: number; personId: string | null | undefined }

export type CohortMembershipChangeOverlay = {
    teamId: number
    personId: string
    cohortId: number
    inCohort: boolean
    // Milliseconds since the epoch, when the change carries a readable version stamp.
    changedAt?: number
}

// A malformed id would fail the whole team's query on the uuid cast, so it reads as no person.
function normalizedPersonId(personId: string | null | undefined): string | null {
    return personId && UUID_REGEX.test(personId) ? personId.toLowerCase() : null
}

// One retry covers a connection that was slow to open. A longer outage falls back to the next event.
const LOAD_ATTEMPTS = 2

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
                for (let attempt = 1; attempt <= LOAD_ATTEMPTS; attempt++) {
                    try {
                        const loaded = await this.repository.getMemberCohortIdsForPersons(teamId, [...personIds])
                        const team = this.memberCohortIds.get(teamId) ?? new Map<string, number[]>()
                        for (const [personId, cohortIds] of loaded) {
                            team.set(personId, cohortIds)
                        }
                        this.memberCohortIds.set(teamId, team)
                        return
                    } catch (error) {
                        logger.warn('⚠️', 'Cohort membership lookup failed in the subscription matcher', {
                            teamId,
                            attempt,
                            error: String(error),
                        })
                    }
                }
                this.failedTeams.add(teamId)
            })
        )
    }

    /**
     * The person's member cohort ids, or null when they are unknown because the lookup failed or never
     * ran. A person-less event is a non-member of every cohort, as it is for a conditional_branch.
     *
     * Changes apply in order on top of the stored membership. The membership writer reads the same
     * topic in its own consumer group, so the table can still hold the state from before a change.
     */
    cohortIdsFor(
        teamId: number,
        personId: string | null | undefined,
        changes: CohortMembershipChangeOverlay[] = []
    ): number[] | null {
        const id = normalizedPersonId(personId)
        if (!id) {
            return []
        }
        const stored = this.memberCohortIds.get(teamId)?.get(id)
        if (!stored) {
            return null
        }
        if (changes.length === 0) {
            return stored
        }
        const cohortIds = new Set(stored)
        for (const { cohortId, inCohort } of changes) {
            if (inCohort) {
                cohortIds.add(cohortId)
            } else {
                cohortIds.delete(cohortId)
            }
        }
        return [...cohortIds]
    }
}
