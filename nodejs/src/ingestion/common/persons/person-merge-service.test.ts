import { DateTime } from 'luxon'

import { UUIDT } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { createDefaultSyncMergeMode } from './person-merge-types'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

describe('PersonMergeService', () => {
    const teamId = 123
    const timestamp = DateTime.now()

    // Records the interleaving of transaction boundaries and Kafka produce calls so we can assert
    // that produce only happens after the transaction commits (never awaited inside it).
    let events: string[]
    let mockPersonStore: any
    let mockOutputs: any

    function buildPerson(distinctId: string): InternalPerson {
        return {
            id: distinctId,
            uuid: new UUIDT().toString(),
            team_id: teamId,
            properties: {},
            created_at: timestamp,
            version: 0,
            is_identified: false,
            is_user_id: null,
            properties_last_updated_at: {},
            properties_last_operation: {},
            last_seen_at: null,
        } as InternalPerson
    }

    function buildService(): PersonMergeService {
        const context = new PersonContext(
            { uuid: new UUIDT().toString(), event: '$identify', distinct_id: 'target', properties: {} } as any,
            { id: teamId } as any,
            'target',
            timestamp,
            true,
            mockOutputs,
            mockPersonStore,
            0,
            createDefaultSyncMergeMode(),
            false,
            false
        )
        return new PersonMergeService(context)
    }

    beforeEach(() => {
        jest.clearAllMocks()
        events = []

        mockOutputs = {
            produce: jest.fn().mockImplementation(() => {
                events.push('produce')
                return Promise.resolve()
            }),
        }

        mockPersonStore = {
            fetchForUpdate: jest.fn(),
            removeDistinctIdFromCache: jest.fn(),
            inTransaction: jest.fn().mockImplementation(async (_name: string, fn: (tx: any) => Promise<unknown>) => {
                events.push('tx:start')
                const tx = {
                    addPersonlessDistinctIdForMerge: jest.fn().mockResolvedValue(true),
                    addDistinctId: jest
                        .fn()
                        .mockResolvedValue([{ output: 'persons', value: Buffer.from('distinct-id-msg') }]),
                    createPerson: jest.fn().mockImplementation((...args: any[]) => {
                        const uuid = args[7]
                        return Promise.resolve({
                            success: true,
                            created: true,
                            person: { ...buildPerson('created'), uuid },
                            messages: [{ output: 'persons', value: Buffer.from('created-person-msg') }],
                        })
                    }),
                }
                const result = await fn(tx)
                events.push('tx:end')
                return result
            }),
        }
    })

    describe('produce-after-commit', () => {
        it('produces distinct-id messages only after the OneExists transaction commits', async () => {
            // Only the "merge into" person exists, the other distinct id is new.
            mockPersonStore.fetchForUpdate.mockImplementation((_teamId: number, distinctId: string) =>
                Promise.resolve(distinctId === 'target' ? buildPerson('target') : null)
            )

            const result = await buildService().merge('other', 'target', teamId, timestamp)

            expect(result.success).toBe(true)
            expect(events).toEqual(['tx:start', 'tx:end', 'produce'])
        })

        it('produces created-person messages only after the NeitherExist transaction commits', async () => {
            // Neither distinct id points at an existing person, so a person is created in-transaction.
            mockPersonStore.fetchForUpdate.mockResolvedValue(null)

            const result = await buildService().merge('other', 'target', teamId, timestamp)

            expect(result.success).toBe(true)
            expect(events).toEqual(['tx:start', 'tx:end', 'produce'])
        })

        it('surfaces the produce failure through the returned kafkaAck without failing the merge', async () => {
            mockPersonStore.fetchForUpdate.mockImplementation((_teamId: number, distinctId: string) =>
                Promise.resolve(distinctId === 'target' ? buildPerson('target') : null)
            )
            mockOutputs.produce.mockRejectedValue(new Error('kafka is down'))

            const result = await buildService().merge('other', 'target', teamId, timestamp)

            // The transaction committed, so the merge succeeds; the produce outcome is threaded into
            // the ack so it is still awaited before the offset is committed downstream.
            expect(result.success).toBe(true)
            if (result.success) {
                await expect(result.kafkaAck).rejects.toThrow('kafka is down')
            }
        })
    })
})
