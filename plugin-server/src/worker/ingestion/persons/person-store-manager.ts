import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import {
    Hub,
    InternalPerson,
    PersonBatchWritingMode,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
} from '../../../types'
import { TransactionClient } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { BatchWritingPersonsStore, BatchWritingPersonsStoreForBatch } from './batch-writing-person-store'
import { MeasuringPersonsStore, MeasuringPersonsStoreForBatch } from './measuring-person-store'
import { personShadowModeComparisonCounter } from './metrics'
import { fromInternalPerson, toInternalPerson } from './person-update-batch'
import { PersonsStore } from './persons-store'
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
        measuringPerson: InternalPerson | null
        batchPerson: InternalPerson | null
        differences: string[]
    }>
    concurrentModifications: Array<{
        key: string
        type: 'different_outcome' | 'same_outcome'
        measuringPerson: InternalPerson | null
        batchPerson: InternalPerson | null
    }>
}

export class PersonStoreManager {
    private mode: PersonBatchWritingMode

    constructor(
        private hub: Hub,
        private measuringPersonStore: MeasuringPersonsStore,
        private batchWritingPersonStore: BatchWritingPersonsStore
    ) {
        if (hub.PERSON_BATCH_WRITING_MODE === 'SHADOW') {
            // Shadow mode is only applied PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE amount of times (0-100)
            const random = Math.random() * 100
            if (random > hub.PERSON_BATCH_WRITING_SHADOW_MODE_PERCENTAGE) {
                this.mode = 'BATCH'
            } else {
                this.mode = 'SHADOW'
            }
        } else {
            this.mode = hub.PERSON_BATCH_WRITING_MODE
        }
    }

    getPersonStore(): PersonsStore {
        if (this.mode === 'BATCH') {
            return this.batchWritingPersonStore
        }
        return this.measuringPersonStore
    }

    forBatch(): PersonsStoreForBatch {
        if (this.mode === 'SHADOW') {
            return new PersonStoreManagerForBatch(
                this.measuringPersonStore.forBatch() as MeasuringPersonsStoreForBatch,
                this.batchWritingPersonStore.forBatch() as BatchWritingPersonsStoreForBatch
            )
        }
        return this.getPersonStore().forBatch()
    }
}

export class PersonStoreManagerForBatch implements PersonsStoreForBatch {
    private finalStates: Map<string, PersonUpdate | null> = new Map()
    private shadowMetrics: ShadowMetrics

    constructor(
        private measuringStore: MeasuringPersonsStoreForBatch,
        private batchStore: BatchWritingPersonsStoreForBatch
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
        return await this.measuringStore.inTransaction(description, transaction)
    }

    async fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        const measuringResult = await this.measuringStore.fetchForChecking(teamId, distinctId)
        this.batchStore.setCheckCachedPerson(teamId, distinctId, measuringResult)
        return measuringResult
    }

    async fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        const measuringResult = await this.measuringStore.fetchForUpdate(teamId, distinctId)
        // If the batch store doesn't have a cached person for update, set it
        if (this.batchStore.getCachedPersonForUpdate(teamId, distinctId) === undefined) {
            this.batchStore.setCachedPersonForUpdate(
                teamId,
                distinctId,
                measuringResult ? fromInternalPerson(measuringResult, distinctId) : null
            )
        }
        return measuringResult
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
        const measuringResult = await this.measuringStore.createPerson(
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

        if (this.batchStore.getCachedPersonForUpdate(teamId, distinctIds![0].distinctId) === undefined) {
            this.batchStore.setCachedPersonForUpdate(
                teamId,
                distinctIds![0].distinctId,
                fromInternalPerson(measuringResult[0], distinctIds![0].distinctId)
            )
        }

        this.updateFinalState(teamId, distinctIds![0].distinctId, measuringResult[0], false)

        return measuringResult
    }

    async updatePersonForUpdate(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const [[personResult, kafkaMessages, versionDisparity], _] = await Promise.all([
            this.measuringStore.updatePersonForUpdate(person, update, distinctId, tx),
            this.batchStore.updatePersonForUpdate(person, update, distinctId, tx),
        ])

        this.updateFinalState(person.team_id, distinctId, personResult, versionDisparity)
        return [personResult, kafkaMessages, versionDisparity]
    }

    async updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const [[personResult, kafkaMessages, versionDisparity], _] = await Promise.all([
            this.measuringStore.updatePersonForMerge(person, update, distinctId, tx),
            this.batchStore.updatePersonForMerge(person, update, distinctId, tx),
        ])

        this.updateFinalState(person.team_id, distinctId, personResult, versionDisparity)
        return [personResult, kafkaMessages, versionDisparity]
    }

    async deletePerson(person: InternalPerson, distinctId: string, tx?: TransactionClient): Promise<TopicMessage[]> {
        const kafkaMessages = await this.measuringStore.deletePerson(person, distinctId, tx)

        // Clear cache for the person
        this.batchStore.clearCache(person.team_id, distinctId)
        this.updateFinalState(person.team_id, distinctId, null, false)

        return kafkaMessages
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const measuringResult = await this.measuringStore.addDistinctId(person, distinctId, version, tx)
        return measuringResult
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const measuringResult = await this.measuringStore.moveDistinctIds(source, target, distinctId, tx)

        return measuringResult
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: TransactionClient
    ): Promise<void> {
        return this.measuringStore.updateCohortsAndFeatureFlagsForMerge(
            teamID,
            sourcePersonID,
            targetPersonID,
            distinctId,
            tx
        )
    }

    async addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean> {
        return this.measuringStore.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        return this.measuringStore.addPersonlessDistinctIdForMerge(teamId, distinctId, tx)
    }

    async personPropertiesSize(teamId: number, distinctId: string): Promise<number> {
        return await this.measuringStore.personPropertiesSize(teamId, distinctId)
    }

    getShadowMetrics(): ShadowMetrics {
        return this.shadowMetrics
    }

    reportBatch(): void {
        this.measuringStore.reportBatch()
        this.batchStore.reportBatch()

        // Log metrics if available
        if (this.shadowMetrics) {
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
                logger.error('Shadow mode detected logic errors in batch writing store', {
                    logicErrorCount: this.shadowMetrics.logicErrors.length,
                    totalComparisons: this.shadowMetrics.totalComparisons,
                    errorRate: logicErrorRate,
                    sampleErrors: this.shadowMetrics.logicErrors.slice(0, 5).map((error) => ({
                        key: error.key,
                        differences: error.differences,
                        measuringPersonUuid: error.measuringPerson?.uuid,
                        batchPersonUuid: error.batchPerson?.uuid,
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
                        measuringPersonUuid: mod.measuringPerson?.uuid,
                        batchPersonUuid: mod.batchPerson?.uuid,
                    })),
                })
            }
        }
    }

    async flush(): Promise<void> {
        await Promise.resolve(this.compareFinalStates())
    }

    compareFinalStates(): void {
        const batchUpdateCache = this.batchStore.getUpdateCache()

        // Initialize metrics
        this.shadowMetrics.totalComparisons = 0
        this.shadowMetrics.sameOutcomeSameBatch = 0
        this.shadowMetrics.differentOutcomeSameBatch = 0
        this.shadowMetrics.differentOutcomeDifferentBatch = 0
        this.shadowMetrics.sameOutcomeDifferentBatch = 0
        this.shadowMetrics.logicErrors = []
        this.shadowMetrics.concurrentModifications = []

        // Compare each person we tracked in finalStates with what's in the batch cache
        for (const [key, measuringUpdate] of this.finalStates.entries()) {
            const batchPersonUpdate = batchUpdateCache.get(key)
            const batchPerson = batchPersonUpdate ? toInternalPerson(batchPersonUpdate) : null
            const measuringPerson = measuringUpdate?.person || null
            const versionDisparity = measuringUpdate?.versionDisparity || false

            this.shadowMetrics.totalComparisons++

            // Compare outcomes (excluding version for primary comparison)
            const measuringComparable = this.getComparablePerson(measuringPerson)
            const batchComparable = this.getComparablePerson(batchPerson)
            const sameOutcome = this.deepEqual(measuringComparable, batchComparable)

            if (sameOutcome && !versionDisparity) {
                // Same outcome, same batch
                this.shadowMetrics.sameOutcomeSameBatch++
                personShadowModeComparisonCounter.labels('same_outcome_same_batch').inc()
            } else if (!sameOutcome && !versionDisparity) {
                // Different outcome, same batch (LOGIC ERROR!)
                this.shadowMetrics.differentOutcomeSameBatch++
                personShadowModeComparisonCounter.labels('different_outcome_same_batch').inc()
                this.shadowMetrics.logicErrors.push({
                    key,
                    measuringPerson,
                    batchPerson,
                    differences: this.findDifferences(measuringComparable, batchComparable),
                })
            } else if (!sameOutcome && versionDisparity) {
                // Different outcome, different batch (concurrent modification by another pod)
                this.shadowMetrics.differentOutcomeDifferentBatch++
                personShadowModeComparisonCounter.labels('different_outcome_different_batch').inc()
                this.shadowMetrics.concurrentModifications.push({
                    key,
                    type: 'different_outcome',
                    measuringPerson,
                    batchPerson,
                })
            } else if (sameOutcome && versionDisparity) {
                // Same outcome, different batch (concurrent modification by another pod with same result)
                this.shadowMetrics.sameOutcomeDifferentBatch++
                personShadowModeComparisonCounter.labels('same_outcome_different_batch').inc()
                this.shadowMetrics.concurrentModifications.push({
                    key,
                    type: 'same_outcome',
                    measuringPerson,
                    batchPerson,
                })
            }
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
            differences.push(`${path}: ${obj1} !== ${obj2}`)
            return differences
        }

        if (typeof obj1 !== typeof obj2) {
            differences.push(`${path}: type mismatch ${typeof obj1} !== ${typeof obj2}`)
            return differences
        }

        if (typeof obj1 !== 'object') {
            differences.push(`${path}: ${obj1} !== ${obj2}`)
            return differences
        }

        // Handle DateTime objects
        if (obj1?.toISO && obj2?.toISO) {
            if (obj1.toISO() !== obj2.toISO()) {
                differences.push(`${path}: ${obj1.toISO()} !== ${obj2.toISO()}`)
            }
            return differences
        }

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

    getFinalStates(): Map<string, PersonUpdate | null> {
        return this.finalStates
    }
}
