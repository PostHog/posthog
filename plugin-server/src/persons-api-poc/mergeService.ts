import {
    MergeConflict,
    MergeResult,
    Person,
    PersonDistinctIdsApi,
    PersonMergeService,
    PersonPropertiesApi,
    SetMergingSourceResult,
} from './interfaces'

/**
 * Implements person merging with conflict detection for concurrent merge operations.
 *
 * The merge process:
 * 1. Mark target as merging target
 * 2. Mark sources as merging source
 * 3. Copy properties from source persons to target
 * 4. Update distinct ID mappings
 * 5. Delete source persons
 */
export class PersonMergeServiceImpl implements PersonMergeService {
    constructor(
        private personPropertiesApi: PersonPropertiesApi,
        private personDistinctIdsApi: PersonDistinctIdsApi
    ) {}

    async merge(targetDistinctId: string, sourceDistinctIds: string[], version: number): Promise<MergeResult> {
        const conflicts: MergeConflict[] = []

        // 1. Mark target distinct ID as merging target
        //
        // This can return a conflict if:
        // - The target is already a source in another merge operation (merging_source status).
        //   This means someone else is merging this distinct ID into a different target.
        //   The client should perform a transitive merge: instead of merging into this target,
        //   merge into the distinct ID returned in `mergingIntoDistinctId`.
        //
        // - The target is already a target in another merge (merging_target status).
        //   This shouldn't happen if the merge service is sharded by target distinct ID,
        //   since all merges to the same target would go to the same shard and be serialized.
        //   If this occurs, it indicates a cleanup is needed for a stale merge state.
        const targetResult = await this.personDistinctIdsApi.setMergingTarget(targetDistinctId, version)

        if (targetResult.status === 'conflict') {
            conflicts.push({
                type: 'target_is_source_in_another_merge',
                distinctId: targetResult.distinctId,
                personUuid: targetResult.personUuid,
                mergingIntoDistinctId: targetResult.mergingIntoDistinctId,
            })
            return { merged: [], conflicts }
        }

        const targetPersonUuid = targetResult.personUuid

        // 2. Mark all source distinct IDs as merging source
        //
        // Source conflicts are handled differently based on the current merge status:
        //
        // - merging_source: The source is already being merged into another target.
        //   First writer wins, so we drop this source and proceed with the remaining sources.
        //   The conflict is informational only (source_already_merging_elsewhere).
        //
        // - merging_target: The source is currently a target of another merge operation.
        //   We cannot merge it yet because the other merge might change its person UUID.
        //   The client should retry this source later (source_is_merge_target).
        const sourceResults = await this.personDistinctIdsApi.setMergingSource(sourceDistinctIds, version)

        const okResults = sourceResults.filter((r): r is SetMergingSourceResult & { status: 'ok' } => r.status === 'ok')
        const conflictResults = sourceResults.filter(
            (r): r is SetMergingSourceResult & { status: 'conflict' } => r.status === 'conflict'
        )

        for (const r of conflictResults) {
            if (r.currentMergeStatus === 'merging_source') {
                conflicts.push({
                    type: 'source_already_merging_elsewhere',
                    distinctId: r.distinctId,
                    personUuid: r.personUuid,
                })
            } else {
                conflicts.push({
                    type: 'source_is_merge_target',
                    distinctId: r.distinctId,
                    personUuid: r.personUuid,
                })
            }
        }

        if (okResults.length === 0) {
            await this.personDistinctIdsApi.setMerged(targetDistinctId, targetPersonUuid, version)
            return { merged: [], conflicts }
        }

        const validSourceDistinctIds = okResults.map((r) => r.distinctId)

        // 3. Copy properties from source persons to target person
        //
        // We fetch source person properties and merge them into the target. Conflicts are
        // resolved using per-property version numbers - the property with the highest version wins.
        //
        // Note: We may need a different method like `getPersonsForMerge` here, which would
        // lock the source person rows to prevent other processes from updating them after
        // we've copied the properties but before we've deleted the source persons.
        const sourcePersonUuids = [...new Set(okResults.map((info) => info.personUuid))]
        const sourcePersonsMap = await this.personPropertiesApi.getPersons(sourcePersonUuids)
        const sourcePersons: Person[] = []
        for (const sourcePersonUuid of sourcePersonUuids) {
            const sourcePerson = sourcePersonsMap.get(sourcePersonUuid)
            if (sourcePerson) {
                sourcePersons.push(sourcePerson)
            }
        }
        if (sourcePersons.length > 0) {
            await this.personPropertiesApi.mergePersonProperties(targetPersonUuid, sourcePersons)
        }

        // 4. Second phase of distinct ID update - move source distinct IDs to the target person
        //    and mark the merge as finished. After this, the distinct IDs point to the target
        //    person UUID and are no longer in a merging state.
        await Promise.all(
            validSourceDistinctIds.map((distinctId) =>
                this.personDistinctIdsApi.setMerged(distinctId, targetPersonUuid, version)
            )
        )

        // 5. Clear merge status on target (also marks the merge as finished for the target)
        await this.personDistinctIdsApi.setMerged(targetDistinctId, targetPersonUuid, version)

        // Source persons are not deleted here - they will be garbage collected by a separate
        // process that identifies persons with no distinct IDs pointing to them.

        const merged = validSourceDistinctIds.map((distinctId) => ({
            distinctId,
            personUuid: targetPersonUuid,
        }))

        return { merged, conflicts }
    }
}
