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

    it('swallows transient fetch errors in loadJobs and keeps existing jobs', async () => {
        const existingJob = { id: 'job-1', created_at: new Date().toISOString() } as any
        const jobsSpy = jest
            .spyOn(api.externalDataSources, 'jobs')
            .mockResolvedValueOnce([existingJob])
            .mockRejectedValueOnce(new TypeError('Failed to fetch'))

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadJobs()
        }).toDispatchActions(['loadJobsSuccess'])
        expect(logic.values.jobs).toEqual([existingJob])

        await expectLogic(logic, () => {
            logic.actions.loadJobs()
        }).toDispatchActions(['loadJobsSuccess'])

        expect(jobsSpy).toHaveBeenCalledTimes(2)
        // Jobs state is preserved; no loadJobsFailure fired for the TypeError.
        expect(logic.values.jobs).toEqual([existingJob])
    })

    it('surfaces non-network API errors via loadJobsFailure', async () => {
        jest.spyOn(api.externalDataSources, 'jobs').mockRejectedValueOnce(new Error('500 Internal Server Error'))

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadJobs()
        }).toDispatchActions(['loadJobsFailure'])
    })

    it('backs off exponentially when loadJobs keeps failing', async () => {
        // Base behavior: success schedules the next poll at 5s cadence.
        jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValue([])

        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        await expectLogic(logic, () => {
            logic.actions.loadJobs()
        }).toDispatchActions(['loadJobsSuccess'])

        // With zero consecutive failures we re-poll after REFRESH_INTERVAL (5s);
        // 4s should not be enough to trigger the next fetch yet.
        jest.advanceTimersByTime(4000)
        expect(api.externalDataSources.jobs).toHaveBeenCalledTimes(1)

        // Advance the remaining 1s + fake error to accumulate failures. Each
        // consecutive failure doubles the retry delay up to the 60s cap.
        jest.advanceTimersByTime(1000)
        await Promise.resolve()
        expect(api.externalDataSources.jobs).toHaveBeenCalledTimes(2)
    })
})
