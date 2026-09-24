import { PERSONS_OUTPUT } from '~/common/outputs/persons'
import { PersonDeletionPublish, PersonRepository } from '~/common/persons/repositories/person-repository'
import { parseJSON } from '~/common/utils/json-parse'

import { PersonDeletionRepublisher } from './person-deletion-republisher'

jest.mock('~/common/utils/logger')

describe('PersonDeletionRepublisher', () => {
    const pending: PersonDeletionPublish[] = [
        { teamId: 2, personUuid: '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee', personVersion: 107 },
        { teamId: 2, personUuid: '01928bbb-cccc-dddd-eeee-ffffffffffff', personVersion: 3 },
    ]

    function buildRepublisher(repository: Partial<PersonRepository>, produce: jest.Mock) {
        return new PersonDeletionRepublisher(repository as PersonRepository, { produce } as never, {
            intervalMs: 1000,
            graceSeconds: 120,
            batchSize: 10,
        })
    }

    // The whole point of the queue: a deletion whose produce was lost leaves the person
    // alive in ClickHouse, so the record has to turn back into a death document.
    it('produces a death document per claimed record and clears the record', async () => {
        const produce = jest.fn().mockResolvedValue(undefined)
        const clearPersonDeletionPublishes = jest.fn().mockResolvedValue(undefined)
        const republisher = buildRepublisher(
            {
                claimPersonDeletionPublishes: jest.fn().mockResolvedValue(pending),
                clearPersonDeletionPublishes,
            },
            produce
        )

        await expect(republisher.runOnce()).resolves.toBe(2)

        expect(produce).toHaveBeenCalledTimes(2)
        const [output, message] = produce.mock.calls[0]
        expect(output).toBe(PERSONS_OUTPUT)
        expect(message.teamId).toBe(2)
        expect(parseJSON(message.value.toString())).toEqual(
            expect.objectContaining({
                id: pending[0].personUuid,
                team_id: 2,
                is_deleted: 1,
                version: 107,
            })
        )
        expect(clearPersonDeletionPublishes).toHaveBeenCalledWith(2, [pending[0].personUuid])
        expect(clearPersonDeletionPublishes).toHaveBeenCalledWith(2, [pending[1].personUuid])
    })

    // Clearing a record whose death document never reached Kafka would lose the
    // deletion for good, which is the drift this queue exists to prevent.
    it('keeps the record of a deletion whose produce failed', async () => {
        const produce = jest.fn().mockRejectedValue(new Error('broker down'))
        const clearPersonDeletionPublishes = jest.fn().mockResolvedValue(undefined)
        const republisher = buildRepublisher(
            {
                claimPersonDeletionPublishes: jest.fn().mockResolvedValue(pending),
                clearPersonDeletionPublishes,
            },
            produce
        )

        await expect(republisher.runOnce()).resolves.toBe(0)

        expect(clearPersonDeletionPublishes).not.toHaveBeenCalled()
    })

    // A pass that outlives the timer would claim the records the previous pass
    // already holds, and produce every death document twice.
    it('runs one pass at a time', async () => {
        let releaseClaim: (value: PersonDeletionPublish[]) => void = () => {}
        const claimPersonDeletionPublishes = jest
            .fn()
            .mockReturnValueOnce(new Promise<PersonDeletionPublish[]>((resolve) => (releaseClaim = resolve)))
            .mockResolvedValue(pending)
        const republisher = buildRepublisher(
            { claimPersonDeletionPublishes, clearPersonDeletionPublishes: jest.fn() },
            jest.fn().mockResolvedValue(undefined)
        )

        const slowPass = republisher.runOnce()
        await expect(republisher.runOnce()).resolves.toBe(0)
        releaseClaim([])
        await slowPass

        expect(claimPersonDeletionPublishes).toHaveBeenCalledTimes(1)
    })
})
