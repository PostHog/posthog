import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration, BatchExportInterval } from '~/types'

import { batchExportBackfillModalLogic } from './batchExportBackfillModalLogic'
import { batchExportDataLogic } from './batchExportDataLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

const MOCK_BATCH_EXPORT_ID = 'test-export-id'
const MOCK_BACKFILL_ID = 'backfill-uuid-123'

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

describe('batchExportBackfillModalLogic', () => {
    let logic: ReturnType<typeof batchExportBackfillModalLogic.build>

    async function setupLogic(configOverrides: Partial<BatchExportConfiguration> = {}): Promise<void> {
        // eslint-disable-next-line react-hooks/rules-of-hooks -- useMocks is an MSW test helper, not a React hook
        useMocks({
            get: {
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/`]: {
                    ...MOCK_BATCH_EXPORT_CONFIG,
                    ...configOverrides,
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
        const configLogic = batchExportDataLogic({ id: MOCK_BATCH_EXPORT_ID })
        configLogic.mount()
        await expectLogic(configLogic).toFinishAllListeners()
        logic = batchExportBackfillModalLogic({ id: MOCK_BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        jest.spyOn(lemonToast, 'success').mockReturnValue('toast-id')
        jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('submitBackfillForm', () => {
        const submitCases: {
            name: string
            interval: BatchExportInterval
            timezone: string | null
            values: {
                earliest_backfill: boolean
                start_at?: ReturnType<typeof dayjs>
                end_at?: ReturnType<typeof dayjs>
            }
            expectedPayload: { start_at: string | null; end_at: string | null }
        }[] = [
            {
                name: 'hourly export sends ISO datetime strings',
                interval: 'hour',
                timezone: null,
                values: {
                    earliest_backfill: false,
                    start_at: dayjs('2024-01-10T08:00:00Z'),
                    end_at: dayjs('2024-01-15T08:00:00Z'),
                },
                expectedPayload: { start_at: '2024-01-10T08:00:00.000Z', end_at: '2024-01-15T08:00:00.000Z' },
            },
            {
                name: 'earliest_backfill sends a null start date',
                interval: 'hour',
                timezone: null,
                values: {
                    earliest_backfill: true,
                    start_at: undefined,
                    end_at: dayjs('2024-01-15T08:00:00Z'),
                },
                expectedPayload: { start_at: null, end_at: '2024-01-15T08:00:00.000Z' },
            },
            {
                name: 'daily export sends date-only strings',
                interval: 'day',
                timezone: 'UTC',
                values: {
                    earliest_backfill: false,
                    start_at: dayjs.utc('2024-01-10T00:00:00Z'),
                    end_at: dayjs.utc('2024-01-15T00:00:00Z'),
                },
                expectedPayload: { start_at: '2024-01-10', end_at: '2024-01-15' },
            },
        ]

        it.each(submitCases)(
            'creates a backfill with the correct payload: $name',
            async ({ interval, timezone, values, expectedPayload }) => {
                await setupLogic({ interval, timezone })
                const createBackfillSpy = jest
                    .spyOn(api.batchExports, 'createBackfill')
                    .mockResolvedValue({ backfill_id: MOCK_BACKFILL_ID })

                logic.actions.openBackfillModal()
                logic.actions.setBackfillFormValues(values)
                await expectLogic(logic, () => {
                    logic.actions.submitBackfillForm()
                }).toDispatchActions(['closeBackfillModal', 'backfillCreated'])

                expect(createBackfillSpy).toHaveBeenCalledWith(MOCK_BATCH_EXPORT_ID, expectedPayload)
                expect(lemonToast.success).toHaveBeenCalledWith('Backfill created')
                await expectLogic(logic).toMatchValues({ isBackfillModalOpen: false })
            }
        )

        it('does not call the API when required fields are missing', async () => {
            await setupLogic()
            const createBackfillSpy = jest
                .spyOn(api.batchExports, 'createBackfill')
                .mockResolvedValue({ backfill_id: MOCK_BACKFILL_ID })

            logic.actions.setBackfillFormValues({ earliest_backfill: false, start_at: undefined, end_at: undefined })
            logic.actions.submitBackfillForm()
            await expectLogic(logic).toFinishAllListeners()

            expect(createBackfillSpy).not.toHaveBeenCalled()
            expect(lemonToast.success).not.toHaveBeenCalled()
        })
    })

    describe('validation errors', () => {
        const errorCases: {
            name: string
            values: {
                earliest_backfill: boolean
                start_at?: ReturnType<typeof dayjs>
                end_at?: ReturnType<typeof dayjs>
            }
            expectedErrors: { start_at?: string; end_at?: string }
        }[] = [
            {
                name: 'missing start date',
                values: { earliest_backfill: false, start_at: undefined, end_at: dayjs('2024-01-15T08:00:00Z') },
                expectedErrors: { start_at: 'Start date is required' },
            },
            {
                name: 'missing end date',
                values: { earliest_backfill: false, start_at: dayjs('2024-01-10T08:00:00Z'), end_at: undefined },
                expectedErrors: { end_at: 'End date is required' },
            },
            {
                name: 'both dates missing',
                values: { earliest_backfill: false, start_at: undefined, end_at: undefined },
                expectedErrors: { start_at: 'Start date is required', end_at: 'End date is required' },
            },
            {
                name: 'earliest_backfill waives the start date requirement',
                values: { earliest_backfill: true, start_at: undefined, end_at: dayjs('2024-01-15T08:00:00Z') },
                expectedErrors: {},
            },
        ]

        it.each(errorCases)('flags $name', async ({ values, expectedErrors }) => {
            await setupLogic()

            logic.actions.setBackfillFormValues(values)

            expect(logic.values.backfillFormValidationErrors).toEqual(expectedErrors)
        })
    })
})
