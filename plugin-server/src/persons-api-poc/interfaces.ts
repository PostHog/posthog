export interface VersionedProperty {
    value: any
    version: number
}

export interface Person {
    personUuid: string
    properties: Record<string, VersionedProperty>
}

export interface PersonPropertiesApi {
    getPersons(personUuids: string[]): Promise<Map<string, Person>>
    mergePersonProperties(targetPersonUuid: string, sourcePersons: Person[]): Promise<void>
    // Note: deletePerson is not part of this interface - orphaned persons (with no distinct IDs
    // pointing to them) are garbage collected by a separate background process.
}

export interface DistinctIdInfo {
    personUuid: string
    distinctId: string
}

export type SetMergingSourceResult =
    | { status: 'ok'; distinctId: string; personUuid: string }
    | {
          status: 'conflict'
          distinctId: string
          personUuid: string
          currentMergeStatus: 'merging_source' | 'merging_target'
      }

export type SetMergingTargetResult =
    | { status: 'ok'; distinctId: string; personUuid: string }
    | { status: 'conflict'; distinctId: string; personUuid: string; mergingIntoDistinctId: string }

export type MergeConflict =
    | { type: 'source_already_merging_elsewhere'; distinctId: string; personUuid: string }
    | { type: 'source_is_merge_target'; distinctId: string; personUuid: string }
    | {
          type: 'target_is_source_in_another_merge'
          distinctId: string
          personUuid: string
          mergingIntoDistinctId: string
      }

export interface MergeResult {
    merged: DistinctIdInfo[]
    conflicts: MergeConflict[]
}

export interface PersonDistinctIdsApi {
    addPersonDistinctId(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo>
    deletePersonDistinctId(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo>
    setPersonUuid(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo>
    setMergingSource(distinctIds: string[], version: number): Promise<SetMergingSourceResult[]>
    setMergingTarget(distinctId: string, version: number): Promise<SetMergingTargetResult>
    setMerged(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo>
}

export interface PersonMergeService {
    merge(targetDistinctId: string, sourceDistinctIds: string[], version: number): Promise<MergeResult>
}
