import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sourceSchemasModalLogic } from './sourceSchemasModalLogic'

// Dispatching loadSourceSchemas doesn't reach the MSW resolver synchronously - the API client and
// fetch layers each add a microtask hop. Poll for the resolver having registered itself rather than
// waiting a fixed duration, so this stays deterministic regardless of how many hops there are.
async function waitUntilPending(pending: Record<string, unknown>, sourceId: string): Promise<void> {
    for (let i = 0; i < 20 && !pending[sourceId]; i++) {
        await Promise.resolve()
    }
}

describe('sourceSchemasModalLogic', () => {
    let logic: ReturnType<typeof sourceSchemasModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-source-schemas/': ({ request }) => {
                    const sourceId = new URL(request.url).searchParams.get('source_id')
                    return [200, { schemas: [{ schema_id: 'schema-1', source_id: sourceId }] }]
                },
            },
        })
        initKeaTests()
        logic = sourceSchemasModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // activeSource doubles as the modal's isOpen flag, so a wiring slip here leaves the modal
    // stuck open (or shows the wrong source's schemas) rather than just a failed network call.
    it('opens for the clicked source and fetches its schemas', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSourceSchemas({ sourceId: 'stripe-1', sourceName: 'Stripe' })
        }).toDispatchActions(['loadSourceSchemas', 'loadSourceSchemasSuccess'])

        expect(logic.values.activeSource).toEqual({ sourceId: 'stripe-1', sourceName: 'Stripe' })
        expect(logic.values.sourceSchemas).toEqual([{ schema_id: 'schema-1', source_id: 'stripe-1' }])
    })

    it('closes back to no active source', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSourceSchemas({ sourceId: 'stripe-1', sourceName: 'Stripe' })
        }).toDispatchActions(['loadSourceSchemasSuccess'])

        logic.actions.closeSourceSchemasModal()

        expect(logic.values.activeSource).toBeNull()
    })

    it('switches to a different source without leaking the previous one', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSourceSchemas({ sourceId: 'stripe-1', sourceName: 'Stripe' })
        }).toDispatchActions(['loadSourceSchemasSuccess'])

        await expectLogic(logic, () => {
            logic.actions.loadSourceSchemas({ sourceId: 'postgres-1', sourceName: 'Postgres' })
        }).toDispatchActions(['loadSourceSchemasSuccess'])

        expect(logic.values.activeSource).toEqual({ sourceId: 'postgres-1', sourceName: 'Postgres' })
        expect(logic.values.sourceSchemas).toEqual([{ schema_id: 'schema-1', source_id: 'postgres-1' }])
    })

    // A slower first request can resolve after a faster later one. If the response isn't checked
    // against whichever source is active by the time it lands, the modal ends up showing stale
    // schemas under the new source's title.
    it('does not let an earlier click overwrite a later one that resolved first', async () => {
        const pending: Record<string, { resolve: (body: unknown) => void }> = {}
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-source-schemas/': ({ request }) => {
                    const sourceId = new URL(request.url).searchParams.get('source_id') as string
                    return new Promise((resolve) => {
                        pending[sourceId] = { resolve: (body) => resolve([200, body]) }
                    })
                },
            },
        })

        logic.actions.loadSourceSchemas({ sourceId: 'source-a', sourceName: 'A' })
        logic.actions.loadSourceSchemas({ sourceId: 'source-b', sourceName: 'B' })
        await waitUntilPending(pending, 'source-a')
        await waitUntilPending(pending, 'source-b')

        // B (the later click) resolves first...
        pending['source-b'].resolve({ schemas: [{ schema_id: 'b-schema' }] })
        await expectLogic(logic).toDispatchActions(['loadSourceSchemasSuccess'])
        // ...then A's slower response arrives after the user has already moved on to B.
        pending['source-a'].resolve({ schemas: [{ schema_id: 'a-schema' }] })
        await expectLogic(logic).toDispatchActions(['loadSourceSchemasSuccess'])

        expect(logic.values.activeSource).toEqual({ sourceId: 'source-b', sourceName: 'B' })
        expect(logic.values.sourceSchemas).toEqual([{ schema_id: 'b-schema' }])
    })

    it('clears schemas and flags an error when the active source fails to load', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-source-schemas/': () => [
                    500,
                    { detail: 'boom' },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSourceSchemas({ sourceId: 'stripe-1', sourceName: 'Stripe' })
        }).toDispatchActions(['loadSourceSchemasSuccess'])

        expect(logic.values.sourceSchemas).toEqual([])
        expect(logic.values.sourceSchemasError).toBe(true)
    })

    it('does not error out the active source over a stale failure from a source already left', async () => {
        const pending: Record<string, { resolve: (response: [number, unknown]) => void }> = {}
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-source-schemas/': ({ request }) => {
                    const sourceId = new URL(request.url).searchParams.get('source_id') as string
                    return new Promise((resolve) => {
                        pending[sourceId] = { resolve }
                    })
                },
            },
        })

        logic.actions.loadSourceSchemas({ sourceId: 'source-a', sourceName: 'A' })
        logic.actions.loadSourceSchemas({ sourceId: 'source-b', sourceName: 'B' })
        await waitUntilPending(pending, 'source-a')
        await waitUntilPending(pending, 'source-b')

        // B (the currently active source) loads successfully...
        pending['source-b'].resolve([200, { schemas: [{ schema_id: 'b-schema' }] }])
        await expectLogic(logic).toDispatchActions(['loadSourceSchemasSuccess'])
        // ...then A's request, for a source the user has already left, fails.
        pending['source-a'].resolve([500, { detail: 'boom' }])
        await expectLogic(logic).toDispatchActions(['loadSourceSchemasSuccess'])

        expect(logic.values.activeSource).toEqual({ sourceId: 'source-b', sourceName: 'B' })
        expect(logic.values.sourceSchemas).toEqual([{ schema_id: 'b-schema' }])
        expect(logic.values.sourceSchemasError).toBe(false)
    })
})
