import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

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
            .mockImplementation(async (_id, schemas) => schemas as ExternalDataSourceSchema[])

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

                    resolve(schemas as ExternalDataSourceSchema[])
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

    it('uses separate logic instances per browser tab', () => {
        expect(sourceSettingsLogic({ id: 'source-1', tabId: 'tab-a' }).key).toEqual('source-1-tab-a')
        expect(sourceSettingsLogic({ id: 'source-1', tabId: 'tab-b' }).key).toEqual('source-1-tab-b')
        expect(sourceSettingsLogic({ id: 'source-1' }).key).toEqual('source-1')
    })

    it('does not load jobs until the syncs tab requests them', async () => {
        const loadJobsSpy = jest.spyOn(api.externalDataSources, 'jobs')

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(loadJobsSpy).not.toHaveBeenCalled()
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

        const serverError = Object.assign(new Error('boom'), { status: 500 })
        jest.spyOn(api.externalDataSources, 'jobs').mockRejectedValueOnce(serverError)

        await expectLogic(logic, () => {
            logic.actions.loadJobs()
        }).toDispatchActions(['loadJobsFailure'])
    })
})
