import { DateTime } from 'luxon'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { extractEventOps } from './person-update'
import { PersonhogPendingRpcError, PersonhogPersonsStore } from './personhog-persons-store'

describe('PersonhogPersonsStore', () => {
    let repository: jest.Mocked<PersonHogPersonWriteRepository>
    let store: PersonhogPersonsStore
    let person: InternalPerson

    const ops = (properties: Record<string, unknown>, event = '$set') =>
        extractEventOps({
            event,
            distinct_id: 'd1',
            properties,
            team_id: 1,
            uuid: 'event-uuid',
            ip: null,
            now: '2026-08-07T00:00:00Z',
            site_url: '',
        } as any)

    beforeEach(() => {
        person = {
            id: '7',
            uuid: 'person-uuid',
            team_id: 1,
            properties: { plan: 'free' },
            created_at: DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
            is_user_id: null,
            is_identified: false,
            last_seen_at: null,
        }
        repository = {
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            updatePersonProperties: jest.fn().mockResolvedValue({ person, updated: true }),
            getDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
            getOrCreatePersonByDistinctId: jest.fn().mockResolvedValue({ person, created: true }),
        } as unknown as jest.Mocked<PersonHogPersonWriteRepository>
        store = new PersonhogPersonsStore(repository)
    })

    it('folds a batch of ops into one leader call per person and returns its message', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' }, $set_once: { first: 'x' } }), 'd1')
        await bound.applyEventOps(person, ops({ $set: { a: '2', first: 'shadowed' } }), 'd1')
        await bound.applyEventOps(person, ops({ $unset: ['gone'] }), 'd1')

        const results = await bound.flush()

        expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.personId).toEqual('7')
        expect(sent.setProperties).toEqual({ a: '2', first: 'shadowed' })
        expect(sent.setOnceProperties).toEqual({})
        expect(sent.unsetProperties).toEqual(['gone'])
        expect(results).toHaveLength(1)
        expect(results[0].messages).toHaveLength(1)
    })

    it('returns a locally projected person while the leader stays authoritative at flush', async () => {
        const bound = store.forBatch(0)
        const eventOps = ops({ $set: { plan: 'pro' }, $set_once: { plan: 'ignored', fresh: 'kept' } })
        eventOps.isIdentified = true
        eventOps.lastSeenAtMs = 7_200_000

        const [projected, messages] = await bound.applyEventOps(person, eventOps, 'd1')

        expect(messages).toEqual([])
        expect(projected.properties).toEqual({ plan: 'pro', fresh: 'kept' })
        expect(projected.is_identified).toBe(true)
        expect(projected.last_seen_at?.toMillis()).toEqual(7_200_000)
        expect(person.properties).toEqual({ plan: 'free' })
    })

    it('does not fold denied events', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }, '$exception'), 'd1')
        const results = await bound.flush()
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
        expect(results).toEqual([])
    })

    it('memoizes strong fetches per batch', async () => {
        repository.fetchPersonsByDistinctIds.mockResolvedValue([{ ...person, distinct_id: 'd1' }])
        const bound = store.forBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        await bound.fetchForUpdate(1, 'd1')
        expect(repository.fetchPersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.fetchPersonsByDistinctIds.mock.calls[0][2]).toEqual({ consistency: 'strong' })
    })

    it('creation resolves through identity and memoizes every distinct id it mapped', async () => {
        const bound = store.forBatch(0)
        const result = await bound.createPerson(
            DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            { initial: 'props' },
            {},
            {},
            1,
            null,
            false,
            'advisory-uuid',
            { distinctId: 'd1' },
            [{ distinctId: 'd2' }]
        )

        expect(result.success).toBe(true)
        expect(repository.getOrCreatePersonByDistinctId).toHaveBeenCalledWith(
            expect.objectContaining({
                teamId: 1,
                distinctId: 'd1',
                extraDistinctIds: ['d2'],
                setProperties: { initial: 'props' },
                createdAtMs: 3_600_000,
            }),
            expect.any(String)
        )
        await bound.fetchForUpdate(1, 'd1')
        await bound.fetchForUpdate(1, 'd2')
        expect(repository.fetchPersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it.each([
        ['not_found', new NoRowsUpdatedError('gone')],
        ['size_violation', new PersonhogPropertiesSizeError('too big', 1, '7')],
    ])('skips %s at flush without failing the batch', async (_outcome, error) => {
        repository.updatePersonProperties.mockRejectedValue(error)
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        const results = await bound.flush()
        expect(results).toEqual([])
    })

    it('fails the flush on unexpected errors so the batch retries whole', async () => {
        repository.updatePersonProperties.mockRejectedValue(new Error('leader unreachable'))
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        await expect(bound.flush()).rejects.toThrow('leader unreachable')
    })

    it('publishes nothing when the leader reports no change', async () => {
        repository.updatePersonProperties.mockResolvedValue({ person, updated: false })
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { plan: 'free' } }), 'd1')
        const results = await bound.flush()
        expect(results).toEqual([])
    })

    it('runs transactions as a passthrough over the store itself', async () => {
        const bound = store.forBatch(0)
        const result = await bound.inTransaction('test', (tx) => {
            expect(tx).toBe(bound)
            return Promise.resolve('done')
        })
        expect(result).toBe('done')
    })

    it.each([
        [
            'updatePersonForMerge',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) =>
                b.updatePersonForMerge(p, {}, 'd1'),
        ],
        [
            'addDistinctId',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) => b.addDistinctId(p, 'd2', 0),
        ],
        [
            'moveDistinctIds',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) =>
                b.moveDistinctIds(p, p, 'd1', undefined, undefined as any),
        ],
        [
            'moveDistinctIdsFromPersons',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) =>
                b.moveDistinctIdsFromPersons([p], p, 'd1', undefined as any),
        ],
        [
            'deletePersons',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) => b.deletePersons([p], 'd1'),
        ],
        [
            'deletePerson',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) => b.deletePerson(p, 'd1'),
        ],
    ])('%s fails loudly while the leader RPC is pending', (_method, call) => {
        const bound = store.forBatch(0)
        expect(() => call(bound, person)).toThrow(PersonhogPendingRpcError)
    })

    it('maps a direct diff update onto the folded RPC', async () => {
        const bound = store.forBatch(0)
        const [updated, messages] = await bound.updatePersonWithPropertiesDiffForUpdate(
            person,
            { plan: 'pro' },
            ['gone'],
            { is_identified: true, last_seen_at: DateTime.fromMillis(7_200_000, { zone: 'utc' }) },
            'd1'
        )
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.setProperties).toEqual({ plan: 'pro' })
        expect(sent.unsetProperties).toEqual(['gone'])
        expect(sent.isIdentified).toBe(true)
        expect(sent.lastSeenAtMs).toBe(7_200_000)
        expect(updated).toBe(person)
        expect(messages).toHaveLength(1)
    })

    it('refuses a diff update carrying fields the RPC cannot express', async () => {
        const bound = store.forBatch(0)
        await expect(
            bound.updatePersonWithPropertiesDiffForUpdate(person, {}, [], { created_at: person.created_at }, 'd1')
        ).rejects.toThrow(PersonhogPendingRpcError)
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
    })
})
