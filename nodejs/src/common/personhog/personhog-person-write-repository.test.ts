import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { BatchCallFailedError, GetOrCreateCoalescer } from './get-or-create-coalescer'
import { GetOrCreatePersonEntry, GetOrCreatePersonOutcome, PersonhogIdentityOperations } from './identity'
import { PersonHogPersonWriteRepository } from './personhog-person-write-repository'

describe('PersonHogPersonWriteRepository', () => {
    const entry: GetOrCreatePersonEntry = { teamId: 1, distinctId: 'd', eventName: '$pageview', createdAtMs: 0 }
    const outcome: GetOrCreatePersonOutcome = {
        created: false,
        person: {
            id: '1',
            uuid: 'uuid-1',
            team_id: 1,
            created_at: DateTime.fromMillis(0),
            version: 0,
            is_identified: false,
            is_user_id: null,
            last_seen_at: null,
        },
    }

    function repository(submit: jest.Mock, singular: jest.Mock): PersonHogPersonWriteRepository {
        const identity = { getOrCreatePersonByDistinctId: singular } as unknown as PersonhogIdentityOperations
        const coalescer = { submit } as unknown as GetOrCreateCoalescer
        return new PersonHogPersonWriteRepository({} as never, identity, 'test', coalescer)
    }

    it('retries a key the service refused through the batch', async () => {
        const submit = jest
            .fn()
            .mockRejectedValueOnce(new ConnectError('retry', Code.Aborted))
            .mockResolvedValueOnce(outcome)
        const singular = jest.fn()

        await expect(repository(submit, singular).getOrCreatePersonByDistinctId(entry, 'tag')).resolves.toBe(outcome)

        expect(submit).toHaveBeenCalledTimes(2)
        expect(singular).not.toHaveBeenCalled()
    })

    it('retries singularly once the batch call itself failed', async () => {
        const submit = jest
            .fn()
            .mockRejectedValue(new BatchCallFailedError(new ConnectError('identity unavailable', Code.Unavailable)))
        const singular = jest.fn().mockResolvedValue(outcome)

        await expect(repository(submit, singular).getOrCreatePersonByDistinctId(entry, 'tag')).resolves.toBe(outcome)

        expect(submit).toHaveBeenCalledTimes(1)
        expect(singular).toHaveBeenCalledWith(entry, 'tag')
    })
})
