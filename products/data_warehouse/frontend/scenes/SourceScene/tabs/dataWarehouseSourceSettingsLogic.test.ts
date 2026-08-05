import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { sourceSceneLogic } from '../SourceScene'
import { sourceSettingsLogic } from './sourceSettingsLogic'

jest.mock('lib/api')

const makeSchema = (overrides: Partial<ExternalDataSourceSchema> = {}): ExternalDataSourceSchema => ({
    id: 'schema-1',
    name: 'public.events',
    label: null,
    should_sync: false,
    incremental: false,
    sync_type: null,
    sync_time_of_day: null,
    latest_error: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_frequency: '6hour',
    ...overrides,
    primary_key_columns: overrides.primary_key_columns ?? null,
})

const makeSource = (schemas: ExternalDataSourceSchema[]): ExternalDataSource =>
    ({
        id: 'source-1',
        source_type: 'Postgres',
        prefix: 'warehouse',
        access_method: 'direct',
        schemas,
    }) as ExternalDataSource

describe('sourceSettingsLogic', () => {
    // Safety net for the test that calls silenceKeaLoadersErrors() inline
    afterEach(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof sourceSettingsLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()

        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({})
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(makeSource([makeSchema()]))
        jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValue([])
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('debounces schema saves and only sends the latest queued change', async () => {
        const bulkUpdateSchemasSpy = jest
            .spyOn(api.externalDataSources, 'bulkUpdateSchemas')
            // Mirror the backend: merge the partial payload onto the stored row, return full schemas.
            .mockImplementation(async (_id, schemas) => schemas.map((partial) => ({ ...makeSchema(), ...partial })))

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        logic.actions.updateSchema(makeSchema({ should_sync: true }))
        logic.actions.updateSchema(makeSchema({ should_sync: false }))

        expect(logic.values.source?.schemas[0].should_sync).toBe(false)
        expect(bulkUpdateSchemasSpy).not.toHaveBeenCalled()

        await jest.advanceTimersByTimeAsync(500)

        expect(bulkUpdateSchemasSpy).toHaveBeenCalledTimes(1)
        expect(bulkUpdateSchemasSpy).toHaveBeenLastCalledWith('source-1', [
            expect.objectContaining({ id: 'schema-1', should_sync: false }),
        ])
    })

    it('keeps newer queued changes when an older save resolves later', async () => {
        let resolveFirstRequest: ((schema: ExternalDataSourceSchema) => void) | null = null
        const bulkUpdateSchemasSpy = jest.spyOn(api.externalDataSources, 'bulkUpdateSchemas').mockImplementation(
            (_id, schemas) =>
                new Promise<ExternalDataSourceSchema[]>((resolve) => {
                    if (!resolveFirstRequest) {
                        resolveFirstRequest = (schema) => resolve([schema])
                        return
                    }

                    resolve(schemas.map((partial) => ({ ...makeSchema(), ...partial })))
                })
        )

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        logic.actions.updateSchema(makeSchema({ should_sync: true }))
        await jest.advanceTimersByTimeAsync(500)

        expect(bulkUpdateSchemasSpy).toHaveBeenCalledTimes(1)
        expect(logic.values.source?.schemas[0].should_sync).toBe(true)

        logic.actions.updateSchema(makeSchema({ should_sync: false }))
        expect(logic.values.source?.schemas[0].should_sync).toBe(false)

        const resolveFirstRequestFn: any = resolveFirstRequest
        if (!resolveFirstRequestFn) {
            throw new Error('Expected first schema update request to be pending')
        }

        resolveFirstRequestFn(makeSchema({ should_sync: true }))
        await Promise.resolve()

        expect(logic.values.source?.schemas[0].should_sync).toBe(false)

        await jest.advanceTimersByTimeAsync(500)

        expect(bulkUpdateSchemasSpy).toHaveBeenCalledTimes(2)
        expect(bulkUpdateSchemasSpy).toHaveBeenLastCalledWith('source-1', [
            expect.objectContaining({ id: 'schema-1', should_sync: false }),
        ])
        expect(logic.values.source?.schemas[0].should_sync).toBe(false)
    })

    it('bulk frequency edit sends only the changed field and preserves untouched ones', async () => {
        // Sending enabled_columns (even unchanged) would make the backend wipe the selection, so the
        // PATCH must carry only { id, sync_frequency }.
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(
            makeSource([makeSchema({ sync_type: 'full_refresh', enabled_columns: ['id', 'name'] })])
        )
        const bulkUpdateSchemasSpy = jest
            .spyOn(api.externalDataSources, 'bulkUpdateSchemas')
            // Mirror the real backend: merge the partial payload onto the stored schema, return full rows.
            .mockImplementation(async (_id, schemas) =>
                schemas.map((partial) => ({ ...makeSchema({ enabled_columns: ['id', 'name'] }), ...partial }))
            )

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        logic.actions.bulkSetFrequency(logic.values.source!.schemas, '24hour')
        await jest.advanceTimersByTimeAsync(500)

        expect(bulkUpdateSchemasSpy).toHaveBeenCalledTimes(1)
        expect(bulkUpdateSchemasSpy).toHaveBeenLastCalledWith('source-1', [
            { id: 'schema-1', sync_frequency: '24hour' },
        ])
        expect(logic.values.source?.schemas[0].sync_frequency).toBe('24hour')
        expect(logic.values.source?.schemas[0].enabled_columns).toEqual(['id', 'name'])
    })

    it('sends a changed writable field discovered by diff, not a fixed allowlist', async () => {
        // row_filters isn't in any hardcoded list — guards against regressing to an allowlist that drops it.
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(
            makeSource([makeSchema({ sync_type: 'incremental', incremental_field: 'updated_at' })])
        )
        const bulkUpdateSchemasSpy = jest
            .spyOn(api.externalDataSources, 'bulkUpdateSchemas')
            .mockImplementation(async (_id, schemas) => schemas.map((partial) => ({ ...makeSchema(), ...partial })))

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        const schema = logic.values.source!.schemas[0]
        const row_filters = [{ column: 'amount', operator: '>' as const, value: 100 }]
        logic.actions.updateSchema({ ...schema, row_filters })
        await jest.advanceTimersByTimeAsync(500)

        expect(bulkUpdateSchemasSpy).toHaveBeenLastCalledWith('source-1', [{ id: 'schema-1', row_filters }])
    })

    it('re-sends a failed in-flight edit fields when a newer edit for the same schema is queued', async () => {
        // A failed flush must not lose its fields: the retry re-sends them alongside the newer edit's.
        let rejectFirst: (() => void) | null = null
        let callCount = 0
        const bulkUpdateSchemasSpy = jest
            .spyOn(api.externalDataSources, 'bulkUpdateSchemas')
            .mockImplementation((_id, schemas) => {
                callCount++
                if (callCount === 1) {
                    return new Promise<ExternalDataSourceSchema[]>((_resolve, reject) => {
                        rejectFirst = () => reject(new Error('boom'))
                    })
                }
                return Promise.resolve(schemas.map((partial) => ({ ...makeSchema(), ...partial })))
            })

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        // Edit 1 (should_sync) flushes and goes in-flight.
        logic.actions.updateSchema(makeSchema({ should_sync: true }))
        await jest.advanceTimersByTimeAsync(500)
        expect(bulkUpdateSchemasSpy).toHaveBeenCalledTimes(1)

        // Edit 2 (a different field) is queued while edit 1 is still in-flight.
        logic.actions.updateSchema(makeSchema({ should_sync: true, sync_frequency: '24hour' }))

        // Edit 1 fails — the retry must carry both should_sync and sync_frequency.
        const rejectFirstFn = rejectFirst as unknown as (() => void) | null
        if (!rejectFirstFn) {
            throw new Error('Expected first request to be pending')
        }
        rejectFirstFn()
        await jest.advanceTimersByTimeAsync(500)

        expect(bulkUpdateSchemasSpy).toHaveBeenCalledTimes(2)
        expect(bulkUpdateSchemasSpy).toHaveBeenLastCalledWith('source-1', [
            { id: 'schema-1', should_sync: true, sync_frequency: '24hour' },
        ])
    })

    it('keys the logic by source id', () => {
        expect(sourceSettingsLogic({ id: 'source-1' }).key).toEqual('source-1')
    })

    it('does not load jobs until the syncs tab requests them', async () => {
        const loadJobsSpy = jest.spyOn(api.externalDataSources, 'jobs')

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(loadJobsSpy).not.toHaveBeenCalled()
    })

    it('dispatches breadcrumb name to the sourceSceneLogic for the source', async () => {
        const sceneLogicForSource = sourceSceneLogic({ id: 'managed-source-1' })
        sceneLogicForSource.mount()

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(sceneLogicForSource.values.breadcrumbName).toEqual('warehouse')

        sceneLogicForSource.unmount()
    })

    it.each([408, 502, 503, 504])(
        'treats a %i gateway response from loadJobs as a soft failure (preserves existing jobs, no loadJobsFailure)',
        async (status) => {
            logic = sourceSettingsLogic({ id: 'source-1' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // Prime with a successful response first so we can confirm the soft failure
            // keeps (rather than clears) the previously-loaded jobs.
            const existingJob = { id: 'job-1', created_at: '2026-01-01T00:00:00Z' } as any
            jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValueOnce([existingJob])
            logic.actions.loadJobs()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.jobs).toEqual([existingJob])

            const gatewayError = Object.assign(new Error('gateway'), { status })
            jest.spyOn(api.externalDataSources, 'jobs').mockRejectedValueOnce(gatewayError)

            await expectLogic(logic, () => {
                logic.actions.loadJobs()
            })
                .toDispatchActions(['loadJobsSuccess'])
                .toNotHaveDispatchedActions(['loadJobsFailure'])

            // Existing jobs are preserved and no error surfaced
            expect(logic.values.jobs).toEqual([existingJob])
        }
    )

    it('re-throws non-transient errors from loadJobs so the failure path runs', async () => {
        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // Deliberate loader failure — kea-loaders would log it
        silenceKeaLoadersErrors()
        const serverError = Object.assign(new Error('boom'), { status: 500 })
        jest.spyOn(api.externalDataSources, 'jobs').mockRejectedValueOnce(serverError)

        await expectLogic(logic, () => {
            logic.actions.loadJobs()
        }).toDispatchActions(['loadJobsFailure'])
    })
})
