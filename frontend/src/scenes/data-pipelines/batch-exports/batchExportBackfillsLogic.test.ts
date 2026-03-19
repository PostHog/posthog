import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration, RawBatchExportBackfill } from '~/types'

import { batchExportBackfillModalLogic } from './batchExportBackfillModalLogic'
import { batchExportBackfillsLogic } from './batchExportBackfillsLogic'
import { batchExportConfigurationLogic } from './batchExportConfigurationLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
        info: jest.fn(),
        warning: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

const MOCK_BATCH_EXPORT_ID = 'test-export-id'
const MOCK_BACKFILL_ID = 'backfill-uuid-123'
// Production polling interval is 1000ms; advance slightly past it to ensure the timer fires
const POLL_ADVANCE_MS = 1100

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

function makeBackfill(overrides: Partial<RawBatchExportBackfill> = {}): RawBatchExportBackfill {
    return {
        id: MOCK_BACKFILL_ID,
        status: 'Running',
        created_at: '2024-01-15T10:00:00Z',
        start_at: '2024-01-10T00:00:00Z',
        end_at: '2024-01-15T00:00:00Z',
        ...overrides,
    }
}

describe('batchExportBackfillsLogic', () => {
    let logic: ReturnType<typeof batchExportBackfillsLogic.build>

    // oxlint-disable-next-line react-hooks/rules-of-hooks -- useMocks is not a React hook
    async function setupLogic(backfillsResponse?: {
        results: RawBatchExportBackfill[]
        next: string | null
    }): Promise<void> {
        useMocks({
            get: {
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/`]: MOCK_BATCH_EXPORT_CONFIG,
                '/api/environments/:team_id/batch_exports/test/': { steps: [] },
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: backfillsResponse ?? {
                    results: [],
                    next: null,
                },
            },
            post: {
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                    backfill_id: MOCK_BACKFILL_ID,
                },
            },
        })
        initKeaTests()
        await expectLogic(teamLogic).toFinishAllListeners()
        const configLogic = batchExportConfigurationLogic({ id: MOCK_BATCH_EXPORT_ID, service: null })
        configLogic.mount()
        await expectLogic(configLogic).toFinishAllListeners()
        logic = batchExportBackfillsLogic({ id: MOCK_BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const modalLogic = batchExportBackfillModalLogic({ id: MOCK_BATCH_EXPORT_ID })
        modalLogic.mount()
    }

    describe('loadBackfills', () => {
        it('loads backfills on mount', async () => {
            await setupLogic()

            await expectLogic(logic).toMatchValues({
                backfillsPaginatedResponse: { results: [], next: null },
            })
        })

        it('parses dates into dayjs objects', async () => {
            await setupLogic({
                results: [makeBackfill({ start_at: '2024-01-10T00:00:00Z', end_at: '2024-01-15T00:00:00Z' })],
                next: null,
            })

            const backfills = logic.values.latestBackfills
            expect(backfills).toHaveLength(1)
            expect(backfills[0].start_at?.isValid()).toBe(true)
            expect(backfills[0].end_at?.isValid()).toBe(true)
        })
    })

    describe('cancelBackfill', () => {
        it('calls cancel API and reloads backfills', async () => {
            await setupLogic()

            const cancelSpy = jest.spyOn(api.batchExports, 'cancelBackfill').mockResolvedValue(undefined as any)

            logic.actions.cancelBackfill({ id: 'backfill-1', status: 'Running' } as any)
            await expectLogic(logic).toFinishAllListeners()

            expect(cancelSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, 'backfill-1')
            expect(lemonToast.success).toHaveBeenCalledWith('Backfill has been cancelled.')
        })

        it('shows error toast on cancel failure', async () => {
            await setupLogic()

            jest.spyOn(api.batchExports, 'cancelBackfill').mockRejectedValue(new Error('Network error'))

            logic.actions.cancelBackfill({ id: 'backfill-1', status: 'Running' } as any)
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to cancel backfill. Please try again.')
        })
    })

    describe('backfillCreated - estimate polling', () => {
        beforeEach(async () => {
            // Init kea logics with real timers, then switch to fake timers for polling
            await setupLogic()
            jest.useFakeTimers()
        })

        afterEach(async () => {
            // Ensure any remaining polling resolves immediately with an estimate so it stops cleanly
            jest.spyOn(api.batchExports, 'getBackfill').mockResolvedValue(makeBackfill({ total_records_count: 1 }))
            for (let i = 0; i < 12; i++) {
                await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            }
            jest.useRealTimers()
        })

        it('shows estimate toast when total_records_count is available on first poll', async () => {
            const getSpy = jest
                .spyOn(api.batchExports, 'getBackfill')
                .mockResolvedValue(makeBackfill({ total_records_count: 42000 }))

            logic.actions.backfillCreated(MOCK_BACKFILL_ID)
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(getSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, MOCK_BACKFILL_ID)
            expect(lemonToast.info).toHaveBeenCalledWith(
                'Estimated ~42,000 rows to export',
                expect.objectContaining({
                    button: expect.objectContaining({
                        label: 'Cancel backfill',
                    }),
                })
            )
        })

        it('shows warning toast with no cancel button when estimate is 0 rows', async () => {
            jest.spyOn(api.batchExports, 'getBackfill').mockResolvedValue(makeBackfill({ total_records_count: 0 }))

            logic.actions.backfillCreated(MOCK_BACKFILL_ID)
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.warning).toHaveBeenCalledWith(
                'No rows found to export for the selected time range. The backfill will finish with nothing to export.'
            )
            expect(lemonToast.info).not.toHaveBeenCalled()
        })

        it('polls until estimate becomes available', async () => {
            const backfillNoEstimate = makeBackfill()

            // Mock the API so that the third call returns an estimate
            const getSpy = jest
                .spyOn(api.batchExports, 'getBackfill')
                .mockResolvedValueOnce(backfillNoEstimate)
                .mockResolvedValueOnce(backfillNoEstimate)
                .mockResolvedValueOnce(makeBackfill({ total_records_count: 5000 }))

            logic.actions.backfillCreated(MOCK_BACKFILL_ID)

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            expect(lemonToast.info).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            expect(lemonToast.info).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(getSpy.mock.calls.length).toBeGreaterThanOrEqual(3)
            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~5,000 rows to export', expect.anything())
        })

        it('gives up after max poll attempts', async () => {
            const getSpy = jest.spyOn(api.batchExports, 'getBackfill').mockResolvedValue(makeBackfill())

            logic.actions.backfillCreated(MOCK_BACKFILL_ID)

            for (let i = 0; i < 10; i++) {
                await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            }

            expect(getSpy.mock.calls.length).toBeGreaterThanOrEqual(10)
            expect(lemonToast.info).not.toHaveBeenCalled()
        })

        it('ignores polling errors and continues', async () => {
            jest.spyOn(api.batchExports, 'getBackfill')
                .mockRejectedValueOnce(new Error('Network error'))
                .mockResolvedValueOnce(makeBackfill({ total_records_count: 3000 }))

            logic.actions.backfillCreated(MOCK_BACKFILL_ID)

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            expect(lemonToast.info).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~3,000 rows to export', expect.anything())
        })

        it('cancel button in toast calls cancel API', async () => {
            jest.spyOn(api.batchExports, 'getBackfill').mockResolvedValue(
                makeBackfill({
                    id: 'backfill-to-cancel',
                    total_records_count: 50000,
                })
            )

            const cancelSpy = jest.spyOn(api.batchExports, 'cancelBackfill').mockResolvedValue(undefined as any)

            logic.actions.backfillCreated(MOCK_BACKFILL_ID)
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            const toastCall = (lemonToast.info as jest.Mock).mock.calls[0]
            const cancelAction = toastCall[1].button.action

            await cancelAction()

            expect(cancelSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, 'backfill-to-cancel')
            expect(lemonToast.success).toHaveBeenCalledWith('Backfill cancelled')
        })
    })
})
