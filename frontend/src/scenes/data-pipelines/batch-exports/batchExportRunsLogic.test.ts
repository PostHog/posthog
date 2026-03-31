import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration, RawBatchExportRun } from '~/types'

import { batchExportBackfillModalLogic } from './batchExportBackfillModalLogic'
import { batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import { batchExportRunsLogic } from './batchExportRunsLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

const MOCK_BATCH_EXPORT_ID = 'test-export-id'

const MOCK_BATCH_EXPORT_CONFIG: BatchExportConfiguration = {
    id: MOCK_BATCH_EXPORT_ID,
    team_id: 997,
    name: 'Test Export',
    destination: {
        type: 'S3',
        config: {
            bucket_name: 'test-bucket',
            region: 'us-east-1',
            prefix: 'events/',
            aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
            aws_secret_access_key: 'secret',
            exclude_events: [],
            include_events: [],
            compression: 'gzip',
            encryption: null,
            kms_key_id: null,
            endpoint_url: null,
            file_format: 'Parquet',
            max_file_size_mb: null,
            use_virtual_style_addressing: false,
        },
    },
    interval: 'hour',
    timezone: null,
    offset_day: null,
    offset_hour: null,
    created_at: '2024-01-01T00:00:00Z',
    start_at: null,
    end_at: null,
    paused: false,
    model: 'events',
    filters: [],
}

function makeRun(overrides: Partial<RawBatchExportRun> = {}): RawBatchExportRun {
    return {
        id: 'run-001',
        status: 'Completed',
        created_at: '2024-01-15T10:00:00Z',
        data_interval_start: '2024-01-15T09:00:00Z',
        data_interval_end: '2024-01-15T10:00:00Z',
        ...overrides,
    }
}

describe('batchExportRunsLogic', () => {
    let logic: ReturnType<typeof batchExportRunsLogic.build>

    // oxlint-disable-next-line react-hooks/rules-of-hooks -- useMocks is not a React hook
    async function setupLogic(runsResponse?: { results: RawBatchExportRun[]; next: string | null }): Promise<void> {
        useMocks({
            get: {
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/`]: MOCK_BATCH_EXPORT_CONFIG,
                '/api/environments/:team_id/batch_exports/test/': { steps: [] },
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/runs/`]: runsResponse ?? {
                    results: [],
                    next: null,
                },
            },
        })
        initKeaTests()
        await expectLogic(teamLogic).toFinishAllListeners()
        const configLogic = batchExportConfigFormLogic({ id: MOCK_BATCH_EXPORT_ID, service: null })
        configLogic.mount()
        await expectLogic(configLogic).toFinishAllListeners()
        const modalLogic = batchExportBackfillModalLogic({ id: MOCK_BATCH_EXPORT_ID })
        modalLogic.mount()
        logic = batchExportRunsLogic({ id: MOCK_BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('loadRuns', () => {
        it('loads runs on mount', async () => {
            await setupLogic()

            await expectLogic(logic).toMatchValues({
                runsPaginatedResponse: { results: [], next: null },
            })
        })

        it('parses dates into dayjs objects in latestRuns', async () => {
            await setupLogic({
                results: [makeRun()],
                next: null,
            })

            const runs = logic.values.latestRuns
            expect(runs).toHaveLength(1)
            expect(runs[0].created_at.toISOString()).toBe('2024-01-15T10:00:00.000Z')
            expect(runs[0].data_interval_start?.toISOString()).toBe('2024-01-15T09:00:00.000Z')
            expect(runs[0].data_interval_end.toISOString()).toBe('2024-01-15T10:00:00.000Z')
        })

        it('groups runs by data interval when not using latest', async () => {
            await setupLogic({
                results: [
                    makeRun({
                        id: 'run-1',
                        data_interval_start: '2024-01-15T09:00:00Z',
                        data_interval_end: '2024-01-15T10:00:00Z',
                    }),
                    makeRun({
                        id: 'run-2',
                        data_interval_start: '2024-01-15T09:00:00Z',
                        data_interval_end: '2024-01-15T10:00:00Z',
                        status: 'Failed',
                    }),
                    makeRun({
                        id: 'run-3',
                        data_interval_start: '2024-01-15T10:00:00Z',
                        data_interval_end: '2024-01-15T11:00:00Z',
                    }),
                ],
                next: null,
            })

            logic.actions.switchLatestRuns(false)
            await expectLogic(logic).toFinishAllListeners()

            const grouped = logic.values.groupedRuns
            expect(grouped).toHaveLength(2)

            // Group with 2 runs sharing the 09:00-10:00 interval
            const group1 = grouped.find((g) => g.runs.length === 2)
            expect(group1).toBeTruthy()
            expect(group1!.data_interval_start.toISOString()).toBe('2024-01-15T09:00:00.000Z')
            expect(group1!.data_interval_end.toISOString()).toBe('2024-01-15T10:00:00.000Z')
            expect(group1!.runs.map((r) => r.id)).toEqual(['run-1', 'run-2'])
            expect(group1!.runs.map((r) => r.status)).toEqual(['Completed', 'Failed'])

            // Group with 1 run for the 10:00-11:00 interval
            const group2 = grouped.find((g) => g.runs.length === 1)
            expect(group2).toBeTruthy()
            expect(group2!.data_interval_start.toISOString()).toBe('2024-01-15T10:00:00.000Z')
            expect(group2!.data_interval_end.toISOString()).toBe('2024-01-15T11:00:00.000Z')
            expect(group2!.runs[0].id).toBe('run-3')
        })
    })

    describe('retryRun', () => {
        it('calls retry API', async () => {
            await setupLogic()

            const retrySpy = jest.spyOn(api.batchExports, 'retryRun').mockResolvedValue(undefined as any)
            const run = makeRun({ id: 'run-to-retry', status: 'Failed' })

            logic.actions.retryRun(run as any)
            await expectLogic(logic).toFinishAllListeners()

            expect(retrySpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, 'run-to-retry')
        })
    })

    describe('cancelRun', () => {
        it('calls cancel API', async () => {
            await setupLogic()

            const cancelSpy = jest.spyOn(api.batchExports, 'cancelRun').mockResolvedValue(undefined as any)
            const run = makeRun({ id: 'run-to-cancel', status: 'Running' })

            logic.actions.cancelRun(run as any)
            await expectLogic(logic).toFinishAllListeners()

            expect(cancelSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, 'run-to-cancel')
        })
    })

    describe('date range', () => {
        it('defaults to latest runs mode', async () => {
            await setupLogic()

            expect(logic.values.usingLatestRuns).toBe(true)
            expect(logic.values.dateRange).toEqual({ from: '-2d', to: null })
        })

        it('reloads runs when date range changes', async () => {
            await setupLogic()

            const loadSpy = jest.spyOn(api.batchExports, 'listRuns').mockResolvedValue({
                results: [],
                next: null,
            } as any)

            logic.actions.switchLatestRuns(false)
            logic.actions.setDateRange('-7d', null)
            await expectLogic(logic).toFinishAllListeners()

            expect(loadSpy).toHaveBeenCalled()
        })
    })
})
