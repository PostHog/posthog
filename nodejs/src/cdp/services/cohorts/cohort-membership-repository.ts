export interface CohortMembershipRepository {
    /**
     * Returns cohort_id -> is_member for every requested cohort; a cohort without a
     * membership row is a non-member. Deliberately no degraded implementation: a failed
     * lookup must surface as an error, never silently answer non-member.
     */
    getMemberships(teamId: number, personUuid: string, cohortIds: number[]): Promise<Map<number, boolean>>
}
