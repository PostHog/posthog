import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sourceSchemasModalLogic } from './sourceSchemasModalLogic'

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
})
