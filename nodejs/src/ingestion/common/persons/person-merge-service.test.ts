import { DateTime } from 'luxon'

import { UUIDT } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { createDefaultSyncMergeMode } from './person-merge-types'

describe('PersonMergeService', () => {
    const teamId = 123
    const timestamp = DateTime.fromISO('2024-01-01T00:00:00Z').toUTC()

    const person = (): InternalPerson =>
        ({
            id: '1',
            uuid: new UUIDT().toString(),
            team_id: teamId,
            properties: {},
            created_at: timestamp,
            version: 0,
            is_identified: true,
            is_user_id: null,
            properties_last_updated_at: {},
            properties_last_operation: {},
            last_seen_at: null,
        }) as unknown as InternalPerson

    function createService(mockPersonStore: any) {
        const context = new PersonContext(
            { uuid: new UUIDT().toString(), event: '$identify', distinct_id: 'main', properties: {} } as any,
            { id: teamId } as any,
            'main',
            timestamp,
            true,
            { produce: jest.fn().mockResolvedValue(undefined) } as any,
            mockPersonStore,
            0,
            createDefaultSyncMergeMode(),
            false,
            false
        )
        return { service: new PersonMergeService(context), context }
    }

    // Guards the produce-after-commit contract: awaiting the Kafka delivery
    // report inside the merge transaction held the Postgres connection and row
    // locks for the produce duration (seconds under producer backpressure) and
    // stalled the sequential per-distinct-id lane.
    it.each([
        [
            'one distinct_id has a person (OneExists)',
            (existing: InternalPerson) => ({
                fetchForUpdate: jest
                    .fn()
                    .mockImplementation((_teamId: number, distinctId: string) =>
                        Promise.resolve(distinctId === 'main' ? existing : null)
                    ),
            }),
        ],
        [
            'neither distinct_id has a person (NeitherExist)',
            () => ({
                fetchForUpdate: jest.fn().mockResolvedValue(null),
            }),
        ],
    ])('produces Kafka messages after the transaction commits when %s', async (_name, makeFetchMock) => {
        const existing = person()
        const events: string[] = []
        let resolveProduce: () => void = () => {}
        const producePending = new Promise<void>((resolve) => {
            resolveProduce = resolve
        })

        const mockTx = {
            addPersonlessDistinctIdForMerge: jest.fn().mockResolvedValue(true),
            addDistinctId: jest
                .fn()
                .mockResolvedValue([{ output: 'persons' as const, value: Buffer.from('distinct-id') }]),
            createPerson: jest.fn().mockResolvedValue({
                success: true,
                person: existing,
                created: true,
                messages: [{ output: 'persons' as const, value: Buffer.from('created') }],
            }),
        }

        const mockPersonStore = {
            ...makeFetchMock(existing),
            inTransaction: jest.fn().mockImplementation(async (_desc: string, cb: (tx: any) => Promise<any>) => {
                events.push('txn-start')
                const result = await cb(mockTx)
                events.push('txn-end')
                return result
            }),
        }

        const { service, context } = createService(mockPersonStore)
        const produceSpy = jest.spyOn(context, 'produceMessages').mockImplementation(() => {
            events.push('produce')
            return producePending
        })

        // merge() resolving while the produce is still pending proves the
        // delivery report is not awaited inline.
        const result = await service.merge('anon', 'main', teamId, timestamp)

        expect(result.success).toBe(true)
        expect(events).toEqual(['txn-start', 'txn-end', 'produce'])
        expect(produceSpy).toHaveBeenCalledTimes(1)

        // The ack is carried on the result for the pipeline's side effects.
        let ackSettled = false
        if (result.success) {
            void result.kafkaAck.then(() => {
                ackSettled = true
            })
        }
        await new Promise((resolve) => setImmediate(resolve))
        expect(ackSettled).toBe(false)
        resolveProduce()
        await new Promise((resolve) => setImmediate(resolve))
        expect(ackSettled).toBe(true)
    })
})
