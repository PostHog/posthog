import { createClient, createRouterTransport } from '@connectrpc/connect'

import {
    GetDistinctIdMappingsRequest,
    GetDistinctIdsForPersonsRequest,
    GetPersonsByDistinctIdsRequest,
    PersonHogIdentity,
} from '~/common/generated/personhog/personhog/identity/v1/identity_pb'

import { PersonhogIdentityOperations } from './identity'

describe('PersonhogIdentityOperations', () => {
    function makeOps(handlers: {
        getPersonsByDistinctIds?: jest.Mock
        getDistinctIdsForPersons?: jest.Mock
        getDistinctIdMappings?: jest.Mock
    }) {
        const transport = createRouterTransport(({ service }) => {
            service(PersonHogIdentity, {
                getOrCreatePersonByDistinctId: jest.fn(() => ({ person: undefined, created: false })),
                getOrCreatePersonsByDistinctIds: jest.fn(() => ({ results: [] })),
                getPersonsByDistinctIds: handlers.getPersonsByDistinctIds ?? jest.fn(() => ({ results: [] })),
                getDistinctIdsForPersons:
                    handlers.getDistinctIdsForPersons ?? jest.fn(() => ({ personDistinctIds: [] })),
                getDistinctIdMappings: handlers.getDistinctIdMappings ?? jest.fn(() => ({ mappings: [] })),
            })
        })
        return new PersonhogIdentityOperations(createClient(PersonHogIdentity, transport))
    }

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

    // The mapping version feeds the ClickHouse message builder as a JSON
    // number; a BigInt leaking through would throw in JSON.stringify.
    it('decodes mapping rows to plain numbers and strings', async () => {
        const handler = jest.fn((req: GetDistinctIdMappingsRequest) => ({
            mappings: req.distinctIds.map((distinctId) => ({
                distinctId,
                personUuid: '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                version: BigInt(1),
            })),
        }))
        const ops = makeOps({ getDistinctIdMappings: handler })

        const mappings = await ops.getDistinctIdMappings(1, ['anon'])

        expect(handler.mock.calls[0][0].teamId).toBe(BigInt(1))
        expect(mappings).toEqual([
            { distinctId: 'anon', personUuid: '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee', version: 1 },
        ])
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
