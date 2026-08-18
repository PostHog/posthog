/**
 * Point lookups for realtime/behavioral cohort membership, backed by the
 * `cohort_membership` table in the behavioral cohorts database. Mirrors the
 * Rust `CohortMembershipProvider` used by feature flags
 * (rust/feature-flags/src/cohorts/membership).
 */
export interface CohortMembershipRepository {
    /**
     * Check membership for a person across multiple cohorts.
     *
     * Returns a map of cohort_id -> is_member covering every requested cohort.
     * A cohort without a membership row is a non-member (`false`) — the write
     * side only ever upserts rows, so absence means the person never entered.
     *
     * There is deliberately no degraded implementation that fakes non-membership:
     * environments without the behavioral cohorts pipeline (e.g. hobby) are kept
     * fail-closed at save time, and a failed lookup must surface as an error
     * rather than silently routing a person as a non-member.
     */
    getMemberships(teamId: number, personUuid: string, cohortIds: number[]): Promise<Map<number, boolean>>
}
