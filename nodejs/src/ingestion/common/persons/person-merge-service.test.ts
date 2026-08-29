import { DateTime } from 'luxon'

import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { PersonMergeResult, createDefaultSyncMergeMode } from './person-merge-types'

describe('PersonMergeService', () => {
    let teamCounter = 1000

    function person(uuid: string, isIdentified: boolean, teamId: number): InternalPerson {
        return {
            id: uuid,
            uuid,
            team_id: teamId,
            properties: {},
            created_at: DateTime.now(),
            version: 0,
            is_identified: isIdentified,
            is_user_id: null,
            last_seen_at: null,
            properties_last_updated_at: {},
            properties_last_operation: {},
        }
    }

    let teamId: number
    let queueMessages: jest.Mock

    beforeEach(() => {
        teamId = teamCounter++
        queueMessages = jest.fn().mockResolvedValue(undefined)
    })

    function service(targetDistinctId: string): PersonMergeService {
        const context = new PersonContext(
            { uuid: 'event-uuid', event: '$identify', distinct_id: targetDistinctId, properties: {} } as any,
            { id: teamId } as any,
            targetDistinctId,
            DateTime.now(),
            true,
            { queueMessages } as any,
            {} as any,
            0,
            createDefaultSyncMergeMode(),
            false,
            false
        )
        return new PersonMergeService(context)
    }

    describe('merge with an illegal distinct id', () => {
        it.each([
            ['target', 'null', 'user'],
            ['source', 'user', 'null'],
        ])(
            'returns before the %s warning is acked and hands the ack back as kafkaAck',
            async (_side, mergeIntoDistinctId, otherPersonDistinctId) => {
                let ackWarning!: () => void
                queueMessages.mockReturnValue(new Promise<void>((resolve) => (ackWarning = resolve)))

                const result = await service(mergeIntoDistinctId).merge(
                    otherPersonDistinctId,
                    mergeIntoDistinctId,
                    teamId,
                    DateTime.now()
                )

                expect(result).toMatchObject({ success: true, person: undefined, needsPersonUpdate: true })
                if (!result.success) {
                    throw new Error('unreachable')
                }
                expect(queueMessages).toHaveBeenCalledWith(INGESTION_WARNINGS_OUTPUT, [{ value: expect.any(Buffer) }])

                let acked = false
                void result.kafkaAck.then(() => (acked = true))
                await Promise.resolve()
                expect(acked).toBe(false)

                ackWarning()
                await result.kafkaAck
                expect(acked).toBe(true)
            }
        )
    })

    describe('mergePeople with an already identified source', () => {
        function refuseMerge(targetDistinctId: string): Promise<PersonMergeResult> {
            return service(targetDistinctId).mergePeople({
                mergeInto: person('target-uuid', true, teamId),
                mergeIntoDistinctId: targetDistinctId,
                otherPerson: person('source-uuid', true, teamId),
                otherPersonDistinctId: 'source',
            })
        }

        it('returns before the warning is acked and hands the ack back as kafkaAck', async () => {
            let ackWarning!: () => void
            queueMessages.mockReturnValue(new Promise<void>((resolve) => (ackWarning = resolve)))

            const result = await refuseMerge('target')

            expect(result).toMatchObject({ success: true, needsPersonUpdate: true })
            if (!result.success) {
                throw new Error('unreachable')
            }
            expect(result.person?.uuid).toBe('target-uuid')
            expect(queueMessages).toHaveBeenCalledWith(INGESTION_WARNINGS_OUTPUT, [{ value: expect.any(Buffer) }])

            let acked = false
            void result.kafkaAck.then(() => (acked = true))
            await Promise.resolve()
            expect(acked).toBe(false)

            ackWarning()
            await result.kafkaAck
            expect(acked).toBe(true)
        })

        it('does not fail the event when the warning produce fails', async () => {
            queueMessages.mockRejectedValue(new Error('broker down'))

            const result = await refuseMerge('target')

            expect(result.success).toBe(true)
            if (result.success) {
                await expect(result.kafkaAck).resolves.toBeUndefined()
            }
        })
    })
})
