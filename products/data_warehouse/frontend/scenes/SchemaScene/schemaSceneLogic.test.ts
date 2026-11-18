import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { ExternalDataSchemaStatus, ExternalDataSchemaWithSource } from '~/types'

import * as warehouseSourcesApi from 'products/warehouse_sources/frontend/generated/api'

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

    it.each([
        ['warehouse source with a CDC engine', 'warehouse', 'postgres', true],
        ['direct query source', 'direct', 'postgres', false],
        ['source type without CDC', 'warehouse', undefined, false],
    ] as const)('sourceSupportsCdc for a %s', async (_, accessMethod, cdcEngine, expected) => {
        jest.spyOn(api.externalDataSchemas, 'get').mockResolvedValue(
            makeSchema({ source: { source_type: 'Postgres', access_method: accessMethod } as any })
        )
        const wizardSpy = jest
            .spyOn(warehouseSourcesApi, 'externalDataSourcesWizardRetrieve')
            .mockResolvedValue({ Postgres: { name: 'Postgres', cdcEngine } } as any)
        logic.actions.loadSchema()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadSourceConfig()
        await expectLogic(logic).toFinishAllListeners()

        expect(wizardSpy).toHaveBeenCalledWith(expect.any(String), { source_type: 'Postgres' })
        expect(logic.values.sourceSupportsCdc).toBe(expected)
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

    it('sends one live query save for a double toggle, with only that field', async () => {
        await expectLogic(logic).toFinishAllListeners()

        let resolveSave: (() => void) | null = null
        const saveSpy = jest
            .spyOn(warehouseSourcesApi, 'externalDataSchemasPartialUpdate')
            .mockReturnValue(new Promise((resolve) => (resolveSave = () => resolve(makeSchema() as any))))

        logic.actions.setLiveQueryEnabled(true)
        logic.actions.setLiveQueryEnabled(true)
        expect(logic.values.savingLiveQuery).toBe(true)

        resolveSave!()
        await expectLogic(logic).toFinishAllListeners()

        expect(saveSpy).toHaveBeenCalledTimes(1)
        expect(saveSpy).toHaveBeenCalledWith(expect.any(String), 'schema-1', { live_query_enabled: true })
        expect(logic.values.savingLiveQuery).toBe(false)
    })

    it('shows the API reason and reloads the schema when a live query save fails', async () => {
        await expectLogic(logic).toFinishAllListeners()

        jest.spyOn(warehouseSourcesApi, 'externalDataSchemasPartialUpdate').mockRejectedValue(
            new Error('This table has no column information yet.')
        )
        const errorToastSpy = jest.spyOn(lemonToast, 'error')
        const getSpy = jest.spyOn(api.externalDataSchemas, 'get')
        getSpy.mockClear()

        logic.actions.setLiveQueryEnabled(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(errorToastSpy).toHaveBeenCalledWith('This table has no column information yet.')
        expect(getSpy).toHaveBeenCalled()
        expect(logic.values.savingLiveQuery).toBe(false)
    })

    it.each([true, false])('confirms a pending schema before enabling when pending is %s', async (pending) => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSchemaSuccess(makeSchema({ should_sync: false, pending_self_managed_table: pending }))

        const updateSpy = jest.spyOn(api.externalDataSchemas, 'update').mockResolvedValue(makeSchema())
        const dialogSpy = jest.spyOn(LemonDialog, 'open').mockImplementation()
        const schema = makeSchema({ should_sync: true, pending_self_managed_table: pending })

        logic.actions.updateSchema(schema)

        if (pending) {
            expect(dialogSpy).toHaveBeenCalledTimes(1)
            expect(updateSpy).not.toHaveBeenCalled()
            const confirm = dialogSpy.mock.calls[0][0].primaryButton?.onClick as () => void
            confirm()
        } else {
            expect(dialogSpy).not.toHaveBeenCalled()
        }

        await expectLogic(logic).toFinishAllListeners()
        expect(updateSpy).toHaveBeenCalledWith('schema-1', expect.objectContaining({ should_sync: true }))
    })
})
