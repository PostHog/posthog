import {
    DistinctIdInfo,
    Person,
    PersonDistinctIdsApi,
    PersonMergeService,
    PersonPropertiesApi,
    SetMergingSourceResult,
    SetMergingTargetResult,
} from './interfaces'

export type ShardingFunction = (key: string, shardCount: number) => number

function defaultShardingFunction(key: string, shardCount: number): number {
    let hash = 0
    for (let i = 0; i < key.length; i++) {
        const char = key.charCodeAt(i)
        hash = (hash << 5) - hash + char
        hash = hash & hash
    }
    return Math.abs(hash) % shardCount
}

export class ShardedPersonPropertiesApi implements PersonPropertiesApi {
    constructor(
        private shards: PersonPropertiesApi[],
        private shardingFunction: ShardingFunction = defaultShardingFunction
    ) {}

    private getShard(personUuid: string): PersonPropertiesApi {
        const shardIndex = this.shardingFunction(personUuid, this.shards.length)
        return this.shards[shardIndex]
    }

    async getPersons(personUuids: string[]): Promise<Map<string, Person>> {
        const shardedUuids = new Map<number, string[]>()
        for (const personUuid of personUuids) {
            const shardIndex = this.shardingFunction(personUuid, this.shards.length)
            const existing = shardedUuids.get(shardIndex) || []
            existing.push(personUuid)
            shardedUuids.set(shardIndex, existing)
        }

        const results = await Promise.all(
            Array.from(shardedUuids.entries()).map(([shardIndex, uuids]) => this.shards[shardIndex].getPersons(uuids))
        )

        const combined = new Map<string, Person>()
        for (const result of results) {
            for (const [uuid, person] of result) {
                combined.set(uuid, person)
            }
        }
        return combined
    }

    async mergePersonProperties(targetPersonUuid: string, sourcePersons: Person[]): Promise<void> {
        return this.getShard(targetPersonUuid).mergePersonProperties(targetPersonUuid, sourcePersons)
    }
}

export class ShardedPersonDistinctIdsApi implements PersonDistinctIdsApi {
    constructor(
        private shards: PersonDistinctIdsApi[],
        private shardingFunction: ShardingFunction = defaultShardingFunction
    ) {}

    private getShard(distinctId: string): PersonDistinctIdsApi {
        const shardIndex = this.shardingFunction(distinctId, this.shards.length)
        return this.shards[shardIndex]
    }

    async addPersonDistinctId(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo> {
        return this.getShard(distinctId).addPersonDistinctId(distinctId, personUuid, version)
    }

    async deletePersonDistinctId(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo> {
        return this.getShard(distinctId).deletePersonDistinctId(distinctId, personUuid, version)
    }

    async setPersonUuid(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo> {
        return this.getShard(distinctId).setPersonUuid(distinctId, personUuid, version)
    }

    async setMergingSource(distinctIds: string[], version: number): Promise<SetMergingSourceResult[]> {
        const shardedDistinctIds = new Map<number, string[]>()
        for (const distinctId of distinctIds) {
            const shardIndex = this.shardingFunction(distinctId, this.shards.length)
            const existing = shardedDistinctIds.get(shardIndex) || []
            existing.push(distinctId)
            shardedDistinctIds.set(shardIndex, existing)
        }

        const results = await Promise.all(
            Array.from(shardedDistinctIds.entries()).map(([shardIndex, ids]) =>
                this.shards[shardIndex].setMergingSource(ids, version)
            )
        )

        return results.flat()
    }

    async setMergingTarget(distinctId: string, version: number): Promise<SetMergingTargetResult> {
        return this.getShard(distinctId).setMergingTarget(distinctId, version)
    }

    async setMerged(distinctId: string, personUuid: string, version: number): Promise<DistinctIdInfo> {
        return this.getShard(distinctId).setMerged(distinctId, personUuid, version)
    }
}

export class ShardedPersonMergeService implements PersonMergeService {
    constructor(
        private shards: PersonMergeService[],
        private shardingFunction: ShardingFunction = defaultShardingFunction
    ) {}

    async merge(targetDistinctId: string, sourceDistinctIds: string[], version: number): Promise<void> {
        const shardedSources = new Map<number, string[]>()

        for (const sourceDistinctId of sourceDistinctIds) {
            const shardIndex = this.shardingFunction(sourceDistinctId, this.shards.length)
            const existing = shardedSources.get(shardIndex) || []
            existing.push(sourceDistinctId)
            shardedSources.set(shardIndex, existing)
        }

        await Promise.all(
            Array.from(shardedSources.entries()).map(([shardIndex, sources]) =>
                this.shards[shardIndex].merge(targetDistinctId, sources, version)
            )
        )
    }
}
