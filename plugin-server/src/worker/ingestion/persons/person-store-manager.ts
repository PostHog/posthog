import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { Hub, InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { TransactionClient } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { BatchWritingPersonsStore, BatchWritingPersonsStoreForBatch } from './batch-writing-person-store'
import { MeasuringPersonsStore, MeasuringPersonsStoreForBatch } from './measuring-person-store'
import { personShadowModeComparisonCounter, personShadowModeReturnIntermediateOutcomeCounter } from './metrics'
import { fromInternalPerson, toInternalPerson } from './person-update-batch'
import { PersonsStoreForBatch } from './persons-store-for-batch'

interface PersonUpdate {
    person: InternalPerson
    versionDisparity: boolean
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
    private finalStates: Map<string, PersonUpdate | null> = new Map()
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

    private getPersonKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private updateFinalState(
        teamId: number,
        distinctId: string,
        person: InternalPerson | null,
        versionDisparity: boolean
    ): void {
        const key = this.getPersonKey(teamId, distinctId)
        this.finalStates.set(key, person ? { person, versionDisparity } : null)
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
        // If the batch store doesn't have a cached person for update, set it
        if (this.secondaryStore.getCachedPersonForUpdate(teamId, distinctId) === undefined) {
            this.secondaryStore.setCachedPersonForUpdate(
                teamId,
                distinctId,
                mainResult ? fromInternalPerson(mainResult, distinctId) : null
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

        if (
            distinctIds &&
            this.secondaryStore.getCachedPersonForUpdate(teamId, distinctIds![0].distinctId) === undefined
        ) {
            this.secondaryStore.setCachedPersonForUpdate(
                teamId,
                distinctIds[0].distinctId,
                fromInternalPerson(mainResult[0], distinctIds![0].distinctId)
            )
        }

        this.updateFinalState(teamId, distinctIds![0].distinctId, mainResult[0], false)

        return mainResult
    }

    async updatePersonForUpdate(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const [[mainPersonResult, mainKafkaMessages, mainVersionDisparity], [secondaryPersonResult]] =
            await Promise.all([
                this.mainStore.updatePersonForUpdate(person, update, distinctId, tx),
                this.secondaryStore.updatePersonForUpdate(person, update, distinctId, tx),
            ])

        // Compare results to ensure consistency between stores
        this.compareUpdateResults(
            'updatePersonForUpdate',
            person.team_id,
            distinctId,
            mainPersonResult,
            secondaryPersonResult,
            mainVersionDisparity
        )

        this.updateFinalState(person.team_id, distinctId, mainPersonResult, mainVersionDisparity)
        return [mainPersonResult, mainKafkaMessages, mainVersionDisparity]
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
            distinctId,
            mainPersonResult,
            secondaryPersonResult,
            mainVersionDisparity
        )

        this.updateFinalState(person.team_id, distinctId, mainPersonResult, mainVersionDisparity)
        return [mainPersonResult, mainKafkaMessages, mainVersionDisparity]
    }

    async deletePerson(person: InternalPerson, distinctId: string, tx?: TransactionClient): Promise<TopicMessage[]> {
        const kafkaMessages = await this.mainStore.deletePerson(person, distinctId, tx)

        // Clear cache for the person
        this.secondaryStore.clearCache(person.team_id, distinctId)
        this.updateFinalState(person.team_id, distinctId, null, false)

        return kafkaMessages
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const mainResult = await this.mainStore.addDistinctId(person, distinctId, version, tx)
        return mainResult
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const mainResult = await this.mainStore.moveDistinctIds(source, target, distinctId, tx)

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
                        mainPersonUuid: error.mainPerson?.uuid,
                        secondaryPersonUuid: error.secondaryPerson?.uuid,
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
                        mainPersonUuid: mod.mainPerson?.uuid,
                        secondaryPersonUuid: mod.secondaryPerson?.uuid,
                    })),
                })
            }
        }
    }

    async flush(): Promise<void> {
        await Promise.resolve(this.compareFinalStates())
    }

    compareFinalStates(): void {
        const batchUpdateCache = this.secondaryStore.getUpdateCache()

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
            const secondaryPersonUpdate = batchUpdateCache.get(key)
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
        distinctId: string,
        mainPerson: InternalPerson,
        secondaryPerson: InternalPerson,
        mainVersionDisparity: boolean
    ): void {
        const key = this.getPersonKey(teamId, distinctId)

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
                distinctId,
                methodName,
                samePersonResult,
                differences,
                mainPersonUuid: mainPerson?.uuid,
                secondaryPersonUuid: secondaryPerson?.uuid,
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

    getFinalStates(): Map<string, PersonUpdate | null> {
        return this.finalStates
    }
}
