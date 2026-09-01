import { createClient, createRouterTransport } from '@connectrpc/connect'

import {
    GetDistinctIdsForPersonsRequest,
    GetPersonsByDistinctIdsRequest,
    MergePersonsRequest,
    PersonHogIdentity,
} from '~/common/generated/personhog/personhog/identity/v1/identity_pb'

import { PersonhogIdentityOperations } from './identity'

describe('PersonhogIdentityOperations', () => {
    function makeOps(handlers: {
        getPersonsByDistinctIds?: jest.Mock
        getDistinctIdsForPersons?: jest.Mock
        mergePersons?: jest.Mock
    }) {
        const transport = createRouterTransport(({ service }) => {
            service(PersonHogIdentity, {
                getOrCreatePersonByDistinctId: jest.fn(() => ({ person: undefined, created: false })),
                getOrCreatePersonsByDistinctIds: jest.fn(() => ({ results: [] })),
                getPersonsByDistinctIds: handlers.getPersonsByDistinctIds ?? jest.fn(() => ({ results: [] })),
                getDistinctIdsForPersons:
                    handlers.getDistinctIdsForPersons ?? jest.fn(() => ({ personDistinctIds: [] })),
                mergePersons: handlers.mergePersons ?? jest.fn(() => ({ opId: '', results: [] })),
            })
        })
        return new PersonhogIdentityOperations(createClient(PersonHogIdentity, transport))
    }

    // Both fields are new on this RPC and nothing else exercises the wire,
    // where a dropped mapping is silent: no newborn would carry its
    // creating event, and every verdict would read as unsettled.
    it('carries the creator event uuid out and the settled bit back', async () => {
        const handler = jest.fn((req: MergePersonsRequest) => ({
            opId: req.opId,
            survivor: {
                id: 7n,
                uuid: 'survivor-uuid',
                teamId: 1n,
                properties: new TextEncoder().encode('{}'),
                createdAt: 3_600_000n,
                version: 1n,
                isIdentified: true,
            },
            results: [{ sourceDistinctId: 'anon-1', outcome: 1, settled: true }],
        }))
        const ops = makeOps({ mergePersons: handler })

        const result = await ops.mergePersons({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'source-event-uuid' }],
            eventSet: {},
            eventSetOnce: {},
            opId: 'op-id',
            allowIdentifiedSources: false,
            moveLimit: 0,
            createdAtMs: 3_600_000,
            creatorEventUuid: 'event-uuid',
        })

        expect(handler.mock.calls[0][0].creatorEventUuid).toBe('event-uuid')
        expect(result.results[0].settled).toBe(true)
        expect(result.survivor?.id).toBe('7')
    })

    it('a merge call carries its own deadline instead of the transport default', async () => {
        // The saga is a multi-step drive bounded server-side at
        // lifecycle_execute_timeout_secs; the transport default is sized
        // for point reads and would cancel drives mid-lease, serializing
        // progress behind lease expiry.
        const client = {
            mergePersons: jest.fn((_req: unknown, _options?: unknown) => Promise.resolve({ opId: '', results: [] })),
        }
        const ops = new PersonhogIdentityOperations(client as never, { mergeTimeoutMs: 35_000 })

        await ops.mergePersons({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'source-event-uuid' }],
            eventSet: {},
            eventSetOnce: {},
            opId: 'op-id',
            allowIdentifiedSources: false,
            moveLimit: 0,
            createdAtMs: 3_600_000,
            creatorEventUuid: 'event-uuid',
        })

        expect(client.mergePersons.mock.calls[0][1]).toMatchObject({ timeoutMs: 35_000 })
    })

    it.each([
        ['an outcome added by a newer service', 99],
        ['no outcome at all, which proto3 reads as zero', 0],
    ])('names %s as unknown rather than as a refusal', async (_case, wire) => {
        // 'error' is a verdict the caller acks and records as a lost merge.
        // Neither of these is a verdict, and the merge may well have
        // happened, so they must not arrive wearing that name.
        const ops = makeOps({
            mergePersons: jest.fn((req: MergePersonsRequest) => ({
                opId: req.opId,
                survivor: undefined,
                results: [{ sourceDistinctId: 'anon-1', outcome: wire }],
            })),
        })

        const result = await ops.mergePersons({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'source-event-uuid' }],
            eventSet: {},
            eventSetOnce: {},
            opId: 'op-id',
            allowIdentifiedSources: false,
            moveLimit: 0,
            createdAtMs: 3_600_000,
            creatorEventUuid: 'event-uuid',
        })

        expect(result.results[0].outcome).toBe('unknown')
    })

    // The identity service rejects batches above 250, so the wrappers must
    // chunk — without this, a large-batch prefetch degrades to a silent
    // no-op on exactly the batches it exists for.
    it('chunks resolve requests to the service batch cap', async () => {
        const handler = jest.fn((req: GetPersonsByDistinctIdsRequest) => ({
            results: req.keys.map((key) => ({ teamId: key.teamId, distinctId: key.distinctId, person: undefined })),
        }))
        const ops = makeOps({ getPersonsByDistinctIds: handler })

        const keys = Array.from({ length: 251 }, (_, i) => ({ teamId: 1, distinctId: `d${i}` }))
        const results = await ops.getPersonsByDistinctIds(keys)

        expect(handler).toHaveBeenCalledTimes(2)
        expect(handler.mock.calls[0][0].keys).toHaveLength(250)
        expect(handler.mock.calls[1][0].keys).toHaveLength(1)
        expect(results).toHaveLength(251)
    })

    it('chunks expansion requests to the service batch cap', async () => {
        const handler = jest.fn((req: GetDistinctIdsForPersonsRequest) => ({
            personDistinctIds: req.personIds.map((id) => ({
                personId: id,
                distinctIds: [{ distinctId: `d-${id}`, version: undefined }],
            })),
        }))
        const ops = makeOps({ getDistinctIdsForPersons: handler })

        const ids = Array.from({ length: 251 }, (_, i) => String(i + 1))
        const byPerson = await ops.getDistinctIdsForPersons(1, ids)

        expect(handler).toHaveBeenCalledTimes(2)
        expect(Object.keys(byPerson)).toHaveLength(251)
    })
})
