export interface CohortMembershipRepository {
    /**
     * The full set of cohort ids the person is currently a member of. Deliberately no
     * degraded implementation: a failed lookup must surface as an error, never silently
     * answer non-member.
     */
    getMemberCohortIds(teamId: number, personUuid: string): Promise<number[]>

    /**
     * The person's stored membership in one cohort, or null when the pipeline never wrote a row
     * for them. A missing row and an out-of-cohort row differ for a "left" trigger: only the second
     * shows the pipeline has recorded the person leaving.
     */
    getCohortMembership(teamId: number, personUuid: string, cohortId: number): Promise<boolean | null>
}
