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
     */
    getMemberships(teamId: number, personUuid: string, cohortIds: number[]): Promise<Map<number, boolean>>
}

/**
 * Used where the behavioral cohorts database is not available (e.g. hobby
 * deploys, where the pool falls back to the main app DB without the
 * `cohort_membership` table). Conservatively reports non-membership.
 */
export class NoOpCohortMembershipRepository implements CohortMembershipRepository {
    getMemberships(_teamId: number, _personUuid: string, cohortIds: number[]): Promise<Map<number, boolean>> {
        return Promise.resolve(new Map(cohortIds.map((id) => [id, false])))
    }
}
