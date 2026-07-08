import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { ExternalDataSchemaStatus, ExternalDataSchemaWithSource } from '~/types'

import { schemaSceneLogic } from './schemaSceneLogic'

jest.mock('lib/api')

const makeSchema = (overrides: Partial<ExternalDataSchemaWithSource> = {}): ExternalDataSchemaWithSource =>
    ({
        id: 'schema-1',
        name: 'public.events',
        label: null,
        should_sync: true,
        incremental: true,
        sync_type: 'incremental',
        status: ExternalDataSchemaStatus.Completed,
        source: { source_type: 'Postgres' },
        ...overrides,
    }) as ExternalDataSchemaWithSource

describe('schemaSceneLogic', () => {
    let logic: ReturnType<typeof schemaSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.externalDataSchemas, 'get').mockResolvedValue(makeSchema())

        logic = schemaSceneLogic({ sourceId: 'source-1', schemaId: 'schema-1' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('resyncSchema toggles the loading flag around the request and resyncs by id', async () => {
        await expectLogic(logic).toFinishAllListeners()

        let resolveResync: (() => void) | null = null
        const resyncSpy = jest
            .spyOn(api.externalDataSchemas, 'resync')
            .mockReturnValue(new Promise<void>((resolve) => (resolveResync = () => resolve())))

        logic.actions.resyncSchema(makeSchema())
        expect(logic.values.resyncingSchema).toBe(true)
        expect(resyncSpy).toHaveBeenCalledWith('schema-1')

        resolveResync!()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.resyncingSchema).toBe(false)
    })

    it('clears the loading flag even when the resync request fails', async () => {
        await expectLogic(logic).toFinishAllListeners()

        jest.spyOn(api.externalDataSchemas, 'resync').mockRejectedValue(new Error('boom'))

        logic.actions.resyncSchema(makeSchema())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.resyncingSchema).toBe(false)
    })

    it('optimistically marks the schema as running when a resync starts', async () => {
        await expectLogic(logic).toFinishAllListeners()

        // Keep the request pending so the optimistic status is observable before loadSchema refetches.
        jest.spyOn(api.externalDataSchemas, 'resync').mockReturnValue(new Promise<void>(() => {}))

        logic.actions.resyncSchema(makeSchema())

        expect(logic.values.schema?.status).toBe(ExternalDataSchemaStatus.Running)
    })
})
