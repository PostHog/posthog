import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { Hub, InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { TransactionClient } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { cloneObject } from '../../../utils/utils'
import { BatchWritingPersonsStore, BatchWritingPersonsStoreForBatch } from './batch-writing-person-store'
import { MeasuringPersonsStore, MeasuringPersonsStoreForBatch } from './measuring-person-store'
import { personShadowModeComparisonCounter, personShadowModeReturnIntermediateOutcomeCounter } from './metrics'
import { fromInternalPerson, toInternalPerson } from './person-update-batch'
import { PersonsStoreForBatch } from './persons-store-for-batch'

interface FinalStateEntry {
    person: InternalPerson
    versionDisparity: boolean
    operations: Array<{
        type: string
        timestamp: number
        distinctId: string
    }>
}

export interface ShadowMetrics {
    totalComparisons: number
    sameOutcomeSameBatch: number
    differentOutcomeSameBatch: number
    differentOutcomeDifferentBatch: number
    sameOutcomeDifferentBatch: number
    logicErrors: Array<{
        key: string
        mainPerson: InternalPerson | null
        secondaryPerson: InternalPerson | null
        differences: string[]
        operations: Array<{
            type: string
            timestamp: number
            distinctId: string
        }>
    }>
    concurrentModifications: Array<{
        key: string
        type: 'different_outcome' | 'same_outcome'
        mainPerson: InternalPerson | null
        secondaryPerson: InternalPerson | null
    }>
}

export class PersonStoreManager {
    constructor(
        private hub: Hub,
        private mainPersonStore: MeasuringPersonsStore,
        private batchWritingPersonStore: BatchWritingPersonsStore
    ) {}

    forBatch(): PersonsStoreForBatch {
        // Shadow mode is only applied PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE amount of times (0-100)
        const random = Math.random() * 100
        if (
            this.hub.PERSON_BATCH_WRITING_MODE === 'SHADOW' &&
            random < this.hub.PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE
        ) {
            return new PersonStoreManagerForBatch(
                this.mainPersonStore.forBatch() as MeasuringPersonsStoreForBatch,
                this.batchWritingPersonStore.forBatch() as BatchWritingPersonsStoreForBatch
            )
        } else if (this.hub.PERSON_BATCH_WRITING_MODE === 'BATCH') {
            return this.batchWritingPersonStore.forBatch()
        }
        return this.mainPersonStore.forBatch()
    }
}

export class PersonStoreManagerForBatch implements PersonsStoreForBatch {
    private finalStates: Map<string, FinalStateEntry | null> = new Map()
    private shadowMetrics: ShadowMetrics

    constructor(
        private mainStore: MeasuringPersonsStoreForBatch,
        private secondaryStore: BatchWritingPersonsStoreForBatch
    ) {
        this.shadowMetrics = {
            totalComparisons: 0,
            sameOutcomeSameBatch: 0,
            differentOutcomeSameBatch: 0,
            differentOutcomeDifferentBatch: 0,
            sameOutcomeDifferentBatch: 0,
            logicErrors: [],
            concurrentModifications: [],
        }
    }

    private getPersonKey(teamId: number, personId: string): string {
        return `${teamId}:${personId}`
    }

    private updateFinalState(
        teamId: number,
        distinctId: string,
        personId: string,
        person: InternalPerson | null,
        versionDisparity: boolean,
        operationType: string,
        version?: number
    ): void {
        const key = this.getPersonKey(teamId, personId)
        const existing = this.finalStates.get(key)

        const operation = {
            type: operationType,
            timestamp: Date.now(),
            distinctId,
            version,
        }

        if (person) {
            this.finalStates.set(key, {
                person,
                versionDisparity,
                operations: existing ? [...existing.operations, operation] : [operation],
            })
        } else {
            this.finalStates.set(key, null)
        }
    }

    async inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.mainStore.inTransaction(description, transaction)
    }

    async fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        const mainResult = await this.mainStore.fetchForChecking(teamId, distinctId)
        this.secondaryStore.setCheckCachedPerson(teamId, distinctId, mainResult)
        return mainResult
    }

    async fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        const mainResult = await this.mainStore.fetchForUpdate(teamId, distinctId)
        // Check if batch store already has cached data for this person
        const existingCached = this.secondaryStore.getCachedPersonForUpdateByDistinctId(teamId, distinctId)

        let versionDisparity = false

        if (mainResult && existingCached === undefined) {
            // No existing cache, set the fresh data
            this.secondaryStore.setCachedPersonForUpdate(teamId, distinctId, fromInternalPerson(mainResult, distinctId))
        } else if (mainResult && existingCached === null) {
            // Cache was explicitly set to null, but now we have data - update it
            this.secondaryStore.setCachedPersonForUpdate(teamId, distinctId, fromInternalPerson(mainResult, distinctId))
        } else if (mainResult && existingCached) {
            // Check for version disparity - if the fetched version differs from cached, another pod updated it
            if (mainResult.version !== existingCached.version) {
                versionDisparity = true
            }

            // We have both fresh data and existing cache - merge them properly
            const freshPersonUpdate = fromInternalPerson(mainResult, distinctId)
            // Preserve the existing property changes
            freshPersonUpdate.properties_to_set = existingCached.properties_to_set
            freshPersonUpdate.properties_to_unset = existingCached.properties_to_unset
            // Preserve the needs_write flag if it was set
            freshPersonUpdate.needs_write = existingCached.needs_write
            freshPersonUpdate.is_identified = freshPersonUpdate.is_identified || existingCached.is_identified

            this.secondaryStore.setCachedPersonForUpdate(teamId, distinctId, freshPersonUpdate)
        } else if (!mainResult) {
            // Main store returned null, ensure secondary is also null
            this.secondaryStore.setCachedPersonForUpdate(teamId, distinctId, null)
        }

        if (mainResult) {
            this.updateFinalState(
                teamId,
                distinctId,
                mainResult.id,
                mainResult,
                versionDisparity,
                'fetchForUpdate',
                mainResult.version
            )
        }

        return mainResult
    }

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        const mainResult = await this.mainStore.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds,
            tx
        )

        if (distinctIds) {
            this.secondaryStore.setCachedPersonForUpdate(
                teamId,
                distinctIds[0].distinctId,
                fromInternalPerson(mainResult[0], distinctIds![0].distinctId)
            )
        }

        this.updateFinalState(
            teamId,
            distinctIds![0].distinctId,
            mainResult[0].id,
            mainResult[0],
            false,
            'createPerson',
            mainResult[0].version
        )

        return mainResult
    }

    async updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const [[mainPersonResult, mainKafkaMessages, mainVersionDisparity], [secondaryPersonResult]] =
            await Promise.all([
                this.mainStore.updatePersonForMerge(person, update, distinctId, tx),
                this.secondaryStore.updatePersonForMerge(person, update, distinctId, tx),
            ])

        // Compare results to ensure consistency between stores
        this.compareUpdateResults(
            'updatePersonForMerge',
            person.team_id,
            person.id,
            mainPersonResult,
            secondaryPersonResult,
            mainVersionDisparity
        )

        this.updateFinalState(
            person.team_id,
            distinctId,
            mainPersonResult.id,
            mainPersonResult,
            mainVersionDisparity,
            'updatePersonForMerge',
            mainPersonResult.version
        )
        return [mainPersonResult, mainKafkaMessages, mainVersionDisparity]
    }

    async updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        // We must make a clone of person since applyEventPropertyUpdates will mutate it
        const personClone = cloneObject(person)
        const [mainPersonResult, mainKafkaMessages, mainVersionDisparity] =
            await this.mainStore.updatePersonWithPropertiesDiffForUpdate(
                personClone,
                propertiesToSet,
                propertiesToUnset,
                otherUpdates,
                distinctId,
                tx
            )

        const [secondaryPersonResult] = await this.secondaryStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            tx
        )

        // Compare results to ensure consistency between stores
        this.compareUpdateResults(
            'updatePersonWithPropertiesDiffForUpdate',
            person.team_id,
            person.id,
            mainPersonResult,
            secondaryPersonResult,
            mainVersionDisparity
        )

        this.updateFinalState(
            person.team_id,
            distinctId,
            mainPersonResult.id,
            mainPersonResult,
            mainVersionDisparity,
            'updatePersonWithPropertiesDiffForUpdate',
            mainPersonResult.version
        )
        return [mainPersonResult, mainKafkaMessages, mainVersionDisparity]
    }

    async deletePerson(person: InternalPerson, distinctId: string, tx?: TransactionClient): Promise<TopicMessage[]> {
        const kafkaMessages = await this.mainStore.deletePerson(person, distinctId, tx)

        // Clear ALL caches related to this person id
        this.secondaryStore.clearAllCachesForPersonId(person.team_id, person.id)
        this.updateFinalState(person.team_id, distinctId, person.id, null, false, 'deletePerson')

        return kafkaMessages
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const mainResult = await this.mainStore.addDistinctId(person, distinctId, version, tx)

        // Cache the person for this new distinct ID in secondary store
        this.secondaryStore.setCachedPersonForUpdate(person.team_id, distinctId, fromInternalPerson(person, distinctId))

        // Track that this distinct ID now points to the person
        this.updateFinalState(person.team_id, distinctId, person.id, person, false, 'addDistinctId', person.version)

        return mainResult
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const mainResult = await this.mainStore.moveDistinctIds(source, target, distinctId, tx)

        // Clear the cache for the source person id to ensure deleted person isn't cached
        this.secondaryStore.clearPersonCacheForPersonId(source.team_id, source.id)

        // Update cache for the target person for the current distinct ID
        // Check if we already have cached data for the target person that includes merged properties
        const existingTargetCache = this.secondaryStore.getCachedPersonForUpdateByPersonId(target.team_id, target.id)
        if (existingTargetCache) {
            // We have existing cached data with merged properties - preserve it
            // Create a new PersonUpdate for this distinctId that preserves the merged data
            const mergedPersonUpdate = { ...existingTargetCache, distinct_id: distinctId }
            this.secondaryStore.setCachedPersonForUpdate(target.team_id, distinctId, mergedPersonUpdate)
            this.updateFinalState(
                target.team_id,
                distinctId,
                target.id,
                toInternalPerson(mergedPersonUpdate),
                false,
                'moveDistinctIds',
                mergedPersonUpdate.version
            )
        } else {
            // No existing cache, create fresh cache from target person
            this.secondaryStore.setCachedPersonForUpdate(
                target.team_id,
                distinctId,
                fromInternalPerson(target, distinctId)
            )
            this.updateFinalState(
                target.team_id,
                distinctId,
                target.id,
                target,
                false,
                'moveDistinctIds',
                target.version
            )
        }

        this.updateFinalState(source.team_id, distinctId, source.id, null, false, 'moveDistinctIds', source.version)

        return mainResult
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: TransactionClient
    ): Promise<void> {
        return this.mainStore.updateCohortsAndFeatureFlagsForMerge(
            teamID,
            sourcePersonID,
            targetPersonID,
            distinctId,
            tx
        )
    }

    async addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean> {
        return this.mainStore.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        return this.mainStore.addPersonlessDistinctIdForMerge(teamId, distinctId, tx)
    }

    async personPropertiesSize(teamId: number, distinctId: string): Promise<number> {
        return await this.mainStore.personPropertiesSize(teamId, distinctId)
    }

    getShadowMetrics(): ShadowMetrics {
        return this.shadowMetrics
    }

    reportBatch(): void {
        this.mainStore.reportBatch()
        this.secondaryStore.reportBatch()

        // Log metrics only if we actually made comparisons
        if (this.shadowMetrics && this.shadowMetrics.totalComparisons > 0) {
            const logicErrorRate =
                this.shadowMetrics.totalComparisons > 0
                    ? (
                          (this.shadowMetrics.differentOutcomeSameBatch / this.shadowMetrics.totalComparisons) *
                          100
                      ).toFixed(2) + '%'
                    : '0%'
            const concurrentModificationRate =
                this.shadowMetrics.totalComparisons > 0
                    ? (
                          ((this.shadowMetrics.differentOutcomeDifferentBatch +
                              this.shadowMetrics.sameOutcomeDifferentBatch) /
                              this.shadowMetrics.totalComparisons) *
                          100
                      ).toFixed(2) + '%'
                    : '0%'

            // Log main metrics with human-readable names
            logger.info('Shadow mode person batch comparison completed', {
                totalComparisons: this.shadowMetrics.totalComparisons,
                sameOutcomeSameBatch: this.shadowMetrics.sameOutcomeSameBatch, // Ideal case - both stores agree
                differentOutcomeSameBatch: this.shadowMetrics.differentOutcomeSameBatch, // Logic errors - these need investigation!
                differentOutcomeDifferentBatch: this.shadowMetrics.differentOutcomeDifferentBatch, // Concurrent writes with different outcomes
                sameOutcomeDifferentBatch: this.shadowMetrics.sameOutcomeDifferentBatch, // Concurrent writes with same outcomes
                logicErrorRate,
                concurrentModificationRate,
            })

            // Log logic errors with high priority
            if (this.shadowMetrics.logicErrors.length > 0) {
                logger.info('Shadow mode detected logic errors in batch writing store', {
                    logicErrorCount: this.shadowMetrics.logicErrors.length,
                    totalComparisons: this.shadowMetrics.totalComparisons,
                    errorRate: logicErrorRate,
                    sampleErrors: this.shadowMetrics.logicErrors.slice(0, 5).map((error) => ({
                        key: error.key,
                        differences: error.differences,
                        mainPersonId: error.mainPerson?.id,
                        secondaryPersonId: error.secondaryPerson?.id,
                        operations: error.operations,
                    })),
                })
            }

            // Log concurrent modifications for awareness
            if (this.shadowMetrics.concurrentModifications.length > 0) {
                logger.warn('Shadow mode detected concurrent modifications during batch processing', {
                    concurrentModificationCount: this.shadowMetrics.concurrentModifications.length,
                    differentOutcomes: this.shadowMetrics.concurrentModifications.filter(
                        (m) => m.type === 'different_outcome'
                    ).length,
                    sameOutcomes: this.shadowMetrics.concurrentModifications.filter((m) => m.type === 'same_outcome')
                        .length,
                    concurrentModificationRate,
                    sampleModifications: this.shadowMetrics.concurrentModifications.slice(0, 3).map((mod) => ({
                        key: mod.key,
                        type: mod.type,
                        mainPersonId: mod.mainPerson?.id,
                        secondaryPersonId: mod.secondaryPerson?.id,
                    })),
                })
            }
        }
    }

    async flush(): Promise<void> {
        await Promise.resolve(this.compareFinalStates())
    }

    compareFinalStates(): void {
        // Initialize metrics
        this.shadowMetrics.totalComparisons = 0
        this.shadowMetrics.sameOutcomeSameBatch = 0
        this.shadowMetrics.differentOutcomeSameBatch = 0
        this.shadowMetrics.differentOutcomeDifferentBatch = 0
        this.shadowMetrics.sameOutcomeDifferentBatch = 0
        this.shadowMetrics.logicErrors = []
        this.shadowMetrics.concurrentModifications = []

        // Compare each person we tracked in finalStates with what's in the batch cache
        for (const [key, mainUpdate] of this.finalStates.entries()) {
            // Skip entries that only have fetchForUpdate operations (read-only, no modifications)
            if (mainUpdate && mainUpdate.operations.length > 0) {
                const hasNonFetchOperations = mainUpdate.operations.some((op) => op.type !== 'fetchForUpdate')
                const lastOperationIsFetch =
                    mainUpdate.operations[mainUpdate.operations.length - 1].type === 'fetchForUpdate'
                if (!hasNonFetchOperations || lastOperationIsFetch) {
                    continue // Skip this entry as it's only fetch operations or last operation overwrote
                }
            }

            // Parse the key to extract teamId and personId
            const [teamIdStr, personId] = key.split(':')
            const teamId = parseInt(teamIdStr, 10)

            const secondaryPersonUpdate = this.secondaryStore.getCachedPersonForUpdateByPersonId(teamId, personId)
            const secondaryPerson = secondaryPersonUpdate ? toInternalPerson(secondaryPersonUpdate) : null
            const mainPerson = mainUpdate?.person || null
            const versionDisparity = mainUpdate?.versionDisparity || false

            this.shadowMetrics.totalComparisons++

            // Compare outcomes (excluding version for primary comparison)
            const mainComparable = this.getComparablePerson(mainPerson)
            const secondaryComparable = this.getComparablePerson(secondaryPerson)
            const sameOutcome = this.deepEqual(mainComparable, secondaryComparable)

            if (sameOutcome && !versionDisparity) {
                // Same outcome, same batch
                this.shadowMetrics.sameOutcomeSameBatch++
                personShadowModeComparisonCounter.labels('true_same_batch').inc()
            } else if (!sameOutcome && !versionDisparity) {
                // Different outcome, same batch (LOGIC ERROR!)
                this.shadowMetrics.differentOutcomeSameBatch++
                personShadowModeComparisonCounter.labels('false_same_batch').inc()
                this.shadowMetrics.logicErrors.push({
                    key,
                    mainPerson,
                    secondaryPerson,
                    differences: this.findDifferences(mainComparable, secondaryComparable),
                    operations: mainUpdate?.operations || [],
                })
            } else if (!sameOutcome && versionDisparity) {
                // Different outcome, different batch (concurrent modification by another pod)
                this.shadowMetrics.differentOutcomeDifferentBatch++
                personShadowModeComparisonCounter.labels('false_different_batch').inc()
                this.shadowMetrics.concurrentModifications.push({
                    key,
                    type: 'different_outcome',
                    mainPerson,
                    secondaryPerson,
                })
            } else if (sameOutcome && versionDisparity) {
                // Same outcome, different batch (concurrent modification by another pod with same result)
                this.shadowMetrics.sameOutcomeDifferentBatch++
                personShadowModeComparisonCounter.labels('true_different_batch').inc()
                this.shadowMetrics.concurrentModifications.push({
                    key,
                    type: 'same_outcome',
                    mainPerson,
                    secondaryPerson,
                })
            }
        }
    }

    private compareUpdateResults(
        methodName: string,
        teamId: number,
        personId: string,
        mainPerson: InternalPerson,
        secondaryPerson: InternalPerson,
        mainVersionDisparity: boolean
    ): void {
        const key = this.getPersonKey(teamId, personId)

        // Compare the person results (excluding version for primary comparison)
        const mainComparable = this.getComparablePerson(mainPerson)
        const secondaryComparable = this.getComparablePerson(secondaryPerson)
        const samePersonResult = this.deepEqual(mainComparable, secondaryComparable)

        if (!samePersonResult) {
            const differences = this.findDifferences(mainComparable, secondaryComparable, 'person')

            // Track inconsistent results in metrics
            personShadowModeReturnIntermediateOutcomeCounter.labels(methodName, 'inconsistent').inc()

            logger.info(`${methodName} returned inconsistent results between stores`, {
                key,
                teamId,
                personId,
                methodName,
                samePersonResult,
                differences,
                mainPersonId: mainPerson?.id,
                secondaryPersonId: secondaryPerson?.id,
                mainVersionDisparity,
            })
        } else {
            // Track consistent results in metrics
            personShadowModeReturnIntermediateOutcomeCounter.labels(methodName, 'consistent').inc()
        }
    }

    private getComparablePerson(person: InternalPerson | null): any {
        if (!person) {
            return null
        }

        // Exclude version and other fields that might differ due to timing
        const { version, ...comparable } = person
        return comparable
    }

    public deepEqual(obj1: any, obj2: any): boolean {
        if (obj1 === obj2) {
            return true
        }
        if (obj1 == null || obj2 == null) {
            return obj1 === obj2
        }
        if (typeof obj1 !== typeof obj2) {
            return false
        }
        if (typeof obj1 !== 'object') {
            return obj1 === obj2
        }

        // Handle arrays
        if (Array.isArray(obj1) && Array.isArray(obj2)) {
            if (obj1.length !== obj2.length) {
                return false
            }
            for (let i = 0; i < obj1.length; i++) {
                if (!this.deepEqual(obj1[i], obj2[i])) {
                    return false
                }
            }
            return true
        }

        // Handle DateTime objects
        if (obj1?.toISO && obj2?.toISO) {
            return obj1.toISO() === obj2.toISO()
        }

        const keys1 = Object.keys(obj1)
        const keys2 = Object.keys(obj2)

        if (keys1.length !== keys2.length) {
            return false
        }

        for (const key of keys1) {
            if (!keys2.includes(key)) {
                return false
            }
            if (!this.deepEqual(obj1[key], obj2[key])) {
                return false
            }
        }

        return true
    }

    public findDifferences(obj1: any, obj2: any, path: string = ''): string[] {
        const differences: string[] = []

        if (obj1 === obj2) {
            return differences
        }
        if (obj1 == null || obj2 == null) {
            differences.push(`${path}: ${this.stringifyValue(obj1)} !== ${this.stringifyValue(obj2)}`)
            return differences
        }

        if (typeof obj1 !== typeof obj2) {
            differences.push(`${path}: type mismatch ${typeof obj1} !== ${typeof obj2}`)
            return differences
        }

        if (typeof obj1 !== 'object') {
            differences.push(`${path}: ${this.stringifyValue(obj1)} !== ${this.stringifyValue(obj2)}`)
            return differences
        }

        // Handle DateTime objects
        if (obj1?.toISO && obj2?.toISO) {
            if (obj1.toISO() !== obj2.toISO()) {
                differences.push(`${path}: ${obj1.toISO()} !== ${obj2.toISO()}`)
            }
            return differences
        }

        // Handle arrays
        if (Array.isArray(obj1) && Array.isArray(obj2)) {
            if (obj1.length !== obj2.length) {
                differences.push(`${path}: array length mismatch ${obj1.length} !== ${obj2.length}`)
            } else {
                for (let i = 0; i < obj1.length; i++) {
                    differences.push(...this.findDifferences(obj1[i], obj2[i], `${path}[${i}]`))
                }
            }
            return differences
        }

        // Handle regular objects
        const keys1 = Object.keys(obj1)
        const keys2 = Object.keys(obj2)
        const allKeys = new Set([...keys1, ...keys2])

        for (const key of allKeys) {
            const newPath = path ? `${path}.${key}` : key
            if (!(key in obj1)) {
                differences.push(`${newPath}: missing in measuring store`)
            } else if (!(key in obj2)) {
                differences.push(`${newPath}: missing in batch store`)
            } else {
                differences.push(...this.findDifferences(obj1[key], obj2[key], newPath))
            }
        }

        return differences
    }

    private stringifyValue(value: any): string {
        if (value === null) {
            return 'null'
        }
        if (value === undefined) {
            return 'undefined'
        }
        if (typeof value === 'string') {
            return `"${value}"`
        }
        if (typeof value === 'number' || typeof value === 'boolean') {
            return String(value)
        }
        if (typeof value === 'function') {
            return '[Function]'
        }
        if (typeof value === 'symbol') {
            return '[Symbol]'
        }
        if (typeof value === 'object') {
            try {
                return JSON.stringify(value)
            } catch (error) {
                return '[Circular or non-serializable object]'
            }
        }
        return String(value)
    }

    getFinalStates(): Map<string, FinalStateEntry | null> {
        return this.finalStates
    }
}
