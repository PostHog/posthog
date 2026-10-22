// pinned: stored as the event of every cohort-triggered run, which workflow steps and logs read
export const COHORT_MEMBERSHIP_CHANGED_EVENT = '$cohort_membership_changed'

// The run event property that carries the version stamp of the change that started a cohort-triggered run.
export const COHORT_MEMBERSHIP_VERSION_PROPERTY = '$membership_version'

export interface CohortMembershipRepository {
    /**
     * The full set of cohort ids the person is currently a member of. Deliberately no
     * degraded implementation: a failed lookup must surface as an error, never silently
     * answer non-member.
     */
    getMemberCohortIds(teamId: number, personUuid: string): Promise<number[]>

    /**
     * getMemberCohortIds for many people in one query, keyed by the lowercase person UUID. Every
     * requested person has an entry, which is empty when the person is in no cohort. The call fails
     * as a whole, for the same reason getMemberCohortIds has no degraded implementation.
     */
    getMemberCohortIdsForPersons(teamId: number, personUuids: string[]): Promise<Map<string, number[]>>

    /**
     * The stored rows of many people for the given cohorts, keyed by the lowercase person UUID and then
     * the cohort id. A person or cohort without a row has no entry. Fails as a whole, as
     * getMemberCohortIdsForPersons does.
     */
    getCohortMembershipsForPersons(
        teamId: number,
        personUuids: string[],
        cohortIds: number[]
    ): Promise<Map<string, Map<number, StoredCohortRow>>>

    /**
     * The person's stored row for one cohort, or null when the pipeline never wrote one.
     * `caughtUp` says whether the row's version stamp is at least `sinceVersion`. It is null when
     * there is nothing to compare: no `sinceVersion`, or a row the writer stored without a stamp.
     */
    getCohortMembership(
        teamId: number,
        personUuid: string,
        cohortId: number,
        sinceVersion?: string
    ): Promise<StoredCohortMembership | null>
}

export interface StoredCohortRow {
    inCohort: boolean
    // The row's version stamp in milliseconds since the epoch, or null when the writer stored it without one.
    version: number | null
}

export interface StoredCohortMembership {
    inCohort: boolean
    caughtUp: boolean | null
}
