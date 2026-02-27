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
        id: 'backfill-1',
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
                    backfill_id: 'temporal-workflow-id',
                },
            },
        })
        initKeaTests()
        await expectLogic(teamLogic).toFinishAllListeners()
        const configLogic = batchExportConfigurationLogic({ id: MOCK_BATCH_EXPORT_ID, service: null })
        configLogic.mount()
        await expectLogic(configLogic).toFinishAllListeners()
        const modalLogic = batchExportBackfillModalLogic({ id: MOCK_BATCH_EXPORT_ID })
        modalLogic.mount()
        logic = batchExportBackfillsLogic({ id: MOCK_BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
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
            // Exhaust any remaining polling iterations to prevent leaking into the next test
            for (let i = 0; i < 12; i++) {
                await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            }
            jest.useRealTimers()
        })

        it('shows estimate toast when total_records_count is available on first poll', async () => {
            const listSpy = jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [
                    makeBackfill({
                        start_at: '2024-01-10T00:00:00Z',
                        end_at: '2024-01-15T00:00:00Z',
                        total_records_count: 42000,
                    }),
                ],
                next: null,
            } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00.000Z', '2024-01-15T00:00:00.000Z')
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(listSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, { ordering: '-created_at' })
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
            jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [
                    makeBackfill({
                        start_at: '2024-01-10T00:00:00Z',
                        end_at: '2024-01-15T00:00:00Z',
                        total_records_count: 0,
                    }),
                ],
                next: null,
            } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00.000Z', '2024-01-15T00:00:00.000Z')
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.warning).toHaveBeenCalledWith(
                'No rows found to export for the selected time range. The backfill will finish with nothing to export.'
            )
            expect(lemonToast.info).not.toHaveBeenCalled()
        })

        it.each([
            {
                description: 'date-only format vs ISO format',
                submittedStart: '2024-01-10',
                submittedEnd: '2024-01-15',
                apiStart: '2024-01-10T00:00:00Z',
                apiEnd: '2024-01-15T00:00:00Z',
            },
            {
                description: 'ISO with milliseconds vs without',
                submittedStart: '2024-01-10T00:00:00.000Z',
                submittedEnd: '2024-01-15T00:00:00.000Z',
                apiStart: '2024-01-10T00:00:00Z',
                apiEnd: '2024-01-15T00:00:00Z',
            },
            {
                description: 'identical formats',
                submittedStart: '2024-01-10T00:00:00Z',
                submittedEnd: '2024-01-15T00:00:00Z',
                apiStart: '2024-01-10T00:00:00Z',
                apiEnd: '2024-01-15T00:00:00Z',
            },
        ])('matches backfill with $description', async ({ submittedStart, submittedEnd, apiStart, apiEnd }) => {
            jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [makeBackfill({ start_at: apiStart, end_at: apiEnd, total_records_count: 1000 })],
                next: null,
            } as any)

            logic.actions.backfillCreated(submittedStart, submittedEnd)
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~1,000 rows to export', expect.anything())
        })

        it('does not match backfill with different dates', async () => {
            jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [
                    makeBackfill({
                        start_at: '2024-02-01T00:00:00Z',
                        end_at: '2024-02-10T00:00:00Z',
                        total_records_count: 5000,
                    }),
                ],
                next: null,
            } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00Z', '2024-01-15T00:00:00Z')

            for (let i = 0; i < 10; i++) {
                await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            }

            expect(lemonToast.info).not.toHaveBeenCalled()
        })

        it('picks the most recent matching backfill when multiple exist', async () => {
            jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [
                    makeBackfill({
                        id: 'backfill-new',
                        start_at: '2024-01-10T00:00:00Z',
                        end_at: '2024-01-15T00:00:00Z',
                        created_at: '2024-01-15T10:00:00Z',
                        total_records_count: 2000,
                    }),
                    makeBackfill({
                        id: 'backfill-old',
                        start_at: '2024-01-10T00:00:00Z',
                        end_at: '2024-01-15T00:00:00Z',
                        created_at: '2024-01-15T08:00:00Z',
                        total_records_count: 1000,
                    }),
                ],
                next: null,
            } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00Z', '2024-01-15T00:00:00Z')
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~2,000 rows to export', expect.anything())
        })

        it('polls until estimate becomes available', async () => {
            const backfillNoEstimate = makeBackfill({
                start_at: '2024-01-10T00:00:00Z',
                end_at: '2024-01-15T00:00:00Z',
            })

            // Mock the API so that the third call returns an estimate
            const listSpy = jest
                .spyOn(api.batchExports, 'listBackfills')
                .mockResolvedValueOnce({ results: [backfillNoEstimate], next: null } as any)
                .mockResolvedValueOnce({ results: [backfillNoEstimate], next: null } as any)
                .mockResolvedValueOnce({
                    results: [
                        makeBackfill({
                            start_at: '2024-01-10T00:00:00Z',
                            end_at: '2024-01-15T00:00:00Z',
                            total_records_count: 5000,
                        }),
                    ],
                    next: null,
                } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00Z', '2024-01-15T00:00:00Z')

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            expect(lemonToast.info).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            expect(lemonToast.info).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            // At least 3 polls (may have extra calls from loadBackfills triggered after finding estimate)
            expect(listSpy.mock.calls.length).toBeGreaterThanOrEqual(3)
            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~5,000 rows to export', expect.anything())
        })

        it('gives up after max poll attempts', async () => {
            const listSpy = jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [makeBackfill({ start_at: '2024-01-10T00:00:00Z', end_at: '2024-01-15T00:00:00Z' })],
                next: null,
            } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00Z', '2024-01-15T00:00:00Z')

            for (let i = 0; i < 10; i++) {
                await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            }

            expect(listSpy.mock.calls.length).toBeGreaterThanOrEqual(10)
            expect(lemonToast.info).not.toHaveBeenCalled()
        })

        it('handles null start_at (earliest backfill)', async () => {
            jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [
                    makeBackfill({ start_at: undefined, end_at: '2024-01-15T00:00:00Z', total_records_count: 100000 }),
                ],
                next: null,
            } as any)

            logic.actions.backfillCreated(null, '2024-01-15T00:00:00Z')
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~100,000 rows to export', expect.anything())
        })

        it('ignores polling errors and continues', async () => {
            jest.spyOn(api.batchExports, 'listBackfills')
                .mockRejectedValueOnce(new Error('Network error'))
                .mockResolvedValueOnce({
                    results: [
                        makeBackfill({
                            start_at: '2024-01-10T00:00:00Z',
                            end_at: '2024-01-15T00:00:00Z',
                            total_records_count: 3000,
                        }),
                    ],
                    next: null,
                } as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00Z', '2024-01-15T00:00:00Z')

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)
            expect(lemonToast.info).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            expect(lemonToast.info).toHaveBeenCalledWith('Estimated ~3,000 rows to export', expect.anything())
        })

        it('cancel button in toast calls cancel API', async () => {
            jest.spyOn(api.batchExports, 'listBackfills').mockResolvedValue({
                results: [
                    makeBackfill({
                        id: 'backfill-to-cancel',
                        start_at: '2024-01-10T00:00:00Z',
                        end_at: '2024-01-15T00:00:00Z',
                        total_records_count: 50000,
                    }),
                ],
                next: null,
            } as any)

            const cancelSpy = jest.spyOn(api.batchExports, 'cancelBackfill').mockResolvedValue(undefined as any)

            logic.actions.backfillCreated('2024-01-10T00:00:00Z', '2024-01-15T00:00:00Z')
            await jest.advanceTimersByTimeAsync(POLL_ADVANCE_MS)

            const toastCall = (lemonToast.info as jest.Mock).mock.calls[0]
            const cancelAction = toastCall[1].button.action

            await cancelAction()

            expect(cancelSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, 'backfill-to-cancel')
            expect(lemonToast.success).toHaveBeenCalledWith('Backfill cancelled')
        })
    })
})
