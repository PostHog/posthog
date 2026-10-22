import { logger } from '~/common/utils/logger'

import { CohortMembershipRepository } from '../cohorts/cohort-membership-repository'

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export type CohortMembershipKey = { teamId: number; personId: string | null | undefined }

export type CohortMembershipChangeOverlay = { teamId: number; personId: string; cohortId: number; inCohort: boolean }

// A malformed id would fail the whole team's query on the uuid cast, so it reads as no person.
function normalizedPersonId(personId: string | null | undefined): string | null {
    return personId && UUID_REGEX.test(personId) ? personId.toLowerCase() : null
}

/**
 * The cohort membership of the people in one subscription matcher batch. load() runs one query per
 * team for the people it has not loaded yet, so every check in the batch reads from memory.
 *
 * Overlays are membership changes that this batch handles. The membership writer reads the same
 * topic in its own consumer group, so the table can still hold the state from before a change. A
 * change is newer than the row it overrides.
 */
export class BatchCohortMembership {
    private memberCohortIds = new Map<number, Map<string, number[]>>()
    private failedTeams = new Set<number>()
    private overlays = new Map<string, Map<number, boolean>>()

    constructor(
        private repository: CohortMembershipRepository,
        overlays: CohortMembershipChangeOverlay[] = []
    ) {
        for (const { teamId, personId, cohortId, inCohort } of overlays) {
            const id = normalizedPersonId(personId)
            if (!id) {
                continue
            }
            const key = `${teamId}:${id}`
            const byCohort = this.overlays.get(key) ?? new Map<number, boolean>()
            byCohort.set(cohortId, inCohort)
            this.overlays.set(key, byCohort)
        }
    }

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
                try {
                    const loaded = await this.repository.getMemberCohortIdsForPersons(teamId, [...personIds])
                    const team = this.memberCohortIds.get(teamId) ?? new Map<string, number[]>()
                    for (const [personId, cohortIds] of loaded) {
                        team.set(personId, cohortIds)
                    }
                    this.memberCohortIds.set(teamId, team)
                } catch (error) {
                    this.failedTeams.add(teamId)
                    logger.warn('⚠️', 'Cohort membership lookup failed in the subscription matcher', {
                        teamId,
                        error: String(error),
                    })
                }
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
        const stored = this.memberCohortIds.get(teamId)?.get(id)
        if (!stored) {
            return null
        }
        const overlay = this.overlays.get(`${teamId}:${id}`)
        if (!overlay) {
            return stored
        }
        const cohortIds = new Set(stored)
        for (const [cohortId, inCohort] of overlay) {
            if (inCohort) {
                cohortIds.add(cohortId)
            } else {
                cohortIds.delete(cohortId)
            }
        }
        return [...cohortIds]
    }
}
