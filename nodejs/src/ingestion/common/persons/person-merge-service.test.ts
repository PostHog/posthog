import { DateTime } from 'luxon'

import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { createDefaultSyncMergeMode } from './person-merge-types'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn(),
}))

const mockEmitIngestionWarning = emitIngestionWarning as jest.MockedFunction<typeof emitIngestionWarning>

describe('PersonMergeService', () => {
    const teamId = 123

    function person(uuid: string, isIdentified: boolean): InternalPerson {
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

    function service(eventName: string): PersonMergeService {
        const context = new PersonContext(
            { uuid: 'event-uuid', event: eventName, distinct_id: 'target', properties: {} } as any,
            { id: teamId } as any,
            'target',
            DateTime.now(),
            true,
            { produce: jest.fn().mockResolvedValue(undefined) } as any,
            {} as any,
            0,
            createDefaultSyncMergeMode(),
            false,
            false
        )
        return new PersonMergeService(context)
    }

    describe('mergePeople with an already identified source', () => {
        let warningResolve: (emitted: boolean) => void

        beforeEach(() => {
            jest.clearAllMocks()
            mockEmitIngestionWarning.mockReturnValue(
                new Promise<boolean>((resolve) => {
                    warningResolve = resolve
                })
            )
        })

        it('returns before the warning is acked and hands the ack back as kafkaAck', async () => {
            const mergeInto = person('target-uuid', true)
            const otherPerson = person('source-uuid', true)

            const result = await service('$identify').mergePeople({
                mergeInto,
                mergeIntoDistinctId: 'target',
                otherPerson,
                otherPersonDistinctId: 'source',
            })

            expect(result).toMatchObject({ success: true, person: mergeInto, needsPersonUpdate: true })
            if (!result.success) {
                throw new Error('unreachable')
            }

            let acked = false
            void result.kafkaAck.then(() => (acked = true))
            await Promise.resolve()
            expect(acked).toBe(false)

            warningResolve(true)
            await result.kafkaAck
            expect(acked).toBe(true)
        })

        it('rate limits the warning per target distinct id', async () => {
            await service('$create_alias').mergePeople({
                mergeInto: person('target-uuid', true),
                mergeIntoDistinctId: 'target',
                otherPerson: person('source-uuid', true),
                otherPersonDistinctId: 'source',
            })

            expect(mockEmitIngestionWarning).toHaveBeenCalledTimes(1)
            const warning = mockEmitIngestionWarning.mock.calls[0][2]
            expect(warning).toMatchObject({ type: 'cannot_merge_already_identified', key: 'target' })
            expect(warning.alwaysSend).toBeUndefined()
        })
    })
})
