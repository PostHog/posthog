export interface CohortMembershipRepository {
    /**
     * The full set of cohort ids the person is currently a member of. Deliberately no
     * degraded implementation: a failed lookup must surface as an error, never silently
     * answer non-member.
     */
    getMemberCohortIds(teamId: number, personUuid: string): Promise<number[]>
}
