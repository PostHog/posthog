import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { userLogic } from 'scenes/userLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    HogQLAlertConfig,
    InsightThresholdType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { alertFormLogic, thresholdAlertHasBounds, type AlertFormType } from './alertFormLogic'
import { alertNotificationLogic } from './alertNotificationLogic'
import { deriveHogQLAlertPreview, HOGQL_ANY_ROW_MAX_ROWS, HOGQL_LAST_ROW_MAX_ROWS } from './hogqlAlertPreview'
import { insightAlertsLogic } from './insightAlertsLogic'
import type { AlertType } from './types'

const Insight42 = '42' as InsightShortId

const TRENDS_QUERY = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: 'total' }],
        trendsFilter: { display: 'ActionsLineGraph' },
    },
}

const makeFormDefaults = (overrides: Partial<AlertFormType> = {}): AlertFormType => ({
    name: 'My alert',
    enabled: true,
    created_by: null,
    created_at: '',
    config: {
        type: 'TrendsAlertConfig',
        series_index: 0,
        check_ongoing_interval: false,
    },
    threshold: {
        configuration: {
            type: InsightThresholdType.ABSOLUTE,
            bounds: { upper: 100 },
        },
    },
    condition: { type: AlertConditionType.ABSOLUTE_VALUE },
    subscribed_users: [],
    checks: [],
    calculation_interval: AlertCalculationInterval.DAILY,
    skip_weekend: false,
    schedule_restriction: null,
    detector_config: null,
    insight: 42,
    ...overrides,
})

const makeSavedAlert = (overrides: Partial<AlertType> = {}): AlertType =>
    ({
        id: 'alert-new-id',
        name: 'My alert',
        enabled: true,
        config: {
            type: 'TrendsAlertConfig',
            series_index: 0,
            check_ongoing_interval: false,
        },
        threshold: {
            configuration: {
                type: InsightThresholdType.ABSOLUTE,
                bounds: { upper: 100 },
            },
        },
        condition: { type: AlertConditionType.ABSOLUTE_VALUE },
        subscribed_users: [],
        checks: [],
        calculation_interval: AlertCalculationInterval.DAILY,
        created_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }) as unknown as AlertType

describe('alertFormLogic', () => {
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: Insight42,
        dashboardId: 1,
        cachedInsight: {
            ...createEmptyInsight(Insight42),
            id: 42,
            query: TRENDS_QUERY,
            alerts: [],
        },
    }

    let createSpy: jest.SpyInstance
    let updateSpy: jest.SpyInstance
    let errorToastSpy: jest.SpyInstance
    let successToastSpy: jest.SpyInstance
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [], count: 0 })
        jest.spyOn(api.alerts, 'get').mockResolvedValue(makeSavedAlert())
        createSpy = jest.spyOn(api.alerts, 'create').mockResolvedValue(makeSavedAlert())
        updateSpy = jest.spyOn(api.alerts, 'update').mockResolvedValue(makeSavedAlert())
        jest.spyOn(api.integrations, 'list').mockResolvedValue({ results: [] } as any)
        errorToastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
        successToastSpy = jest.spyOn(lemonToast, 'success').mockImplementation(jest.fn())
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(jest.fn())

        insightLogic(insightLogicProps).mount()
        insightDataLogic(insightLogicProps).mount()
        insightVizDataLogic(insightLogicProps).mount()
        insightAlertsLogic({ insightId: 42, insightLogicProps, deferInitialAlertsLoad: true }).mount()
        integrationsLogic.mount()
        // Mirror `EditAlertModal`, which mounts `alertNotificationLogic` (keyed `new` for new alerts)
        // via `useValues`. Without this mount, `flushPendingNotifications` throws on the logic lookup
        // and obscures the real post-save behavior we're testing.
        alertNotificationLogic({ alertId: undefined }).mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    function mountForm(onEditSuccess: jest.Mock = jest.fn()): ReturnType<typeof alertFormLogic.build> {
        const logic = alertFormLogic({
            alert: null,
            insightId: 42,
            onEditSuccess,
            insightVizDataLogicProps: insightLogicProps,
            insightInterval: 'day',
        })
        logic.mount()
        logic.actions.setAlertFormValues({ ...makeFormDefaults(), checks: undefined })
        return logic
    }

    it('shows success toast and no error toast when create succeeds', async () => {
        const logic = mountForm()

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        expect(errorToastSpy).not.toHaveBeenCalled()
        expect(successToastSpy).toHaveBeenCalledWith('Alert created.')
    })

    // Regression test for ticket #353:
    // A post-save side-effect (e.g. the parent `onEditSuccess` callback) throwing must NOT surface as
    // "Error saving alert: undefined: undefined" — the alert was already created successfully (HTTP 201).
    it('still shows success toast when a post-save side-effect throws', async () => {
        const postSaveError = new Error('post-save bug: boom')
        const onEditSuccess = jest.fn(() => {
            throw postSaveError
        })

        const logic = mountForm(onEditSuccess)

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        expect(successToastSpy).toHaveBeenCalledWith('Alert created.')
        expect(errorToastSpy).not.toHaveBeenCalled()
        expect(captureExceptionSpy).toHaveBeenCalledWith(postSaveError)
    })

    it.each([
        {
            name: 'a descriptive error toast for a DRF ApiError',
            error: new ApiError('Bad request', 400, undefined, {
                attr: 'calculation_interval',
                detail: 'Must be one of hourly, daily, weekly, monthly',
            }),
            expectedToast: 'Error saving alert: calculation interval: Must be one of hourly, daily, weekly, monthly',
        },
        {
            name: 'the error message for a non-ApiError',
            error: new Error('Network request failed'),
            expectedToast: 'Error saving alert: Network request failed',
        },
        {
            name: 'the ApiError message when attr and detail are missing',
            error: new ApiError('Bad request', 400),
            expectedToast: 'Error saving alert: Bad request',
        },
    ])('shows %s when the create API call fails', async ({ error, expectedToast }) => {
        createSpy.mockRejectedValueOnce(error)

        const logic = mountForm()

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(errorToastSpy).toHaveBeenCalledWith(expectedToast)
        expect(successToastSpy).not.toHaveBeenCalled()
    })

    it('shows success toast and no error toast when update succeeds', async () => {
        const onEditSuccess = jest.fn()
        const existingAlert = makeSavedAlert({ id: 'alert-existing-id' })
        const logic = alertFormLogic({
            alert: existingAlert,
            insightId: 42,
            onEditSuccess,
            insightVizDataLogicProps: insightLogicProps,
            insightInterval: 'day',
        })
        logic.mount()
        logic.actions.setAlertFormValues({ ...makeFormDefaults({ id: existingAlert.id }), checks: undefined })

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(updateSpy).toHaveBeenCalledTimes(1)
        expect(errorToastSpy).not.toHaveBeenCalled()
        expect(successToastSpy).toHaveBeenCalledWith('Alert saved.')
    })

    it('blocks save when threshold alert has no lower or upper bound', async () => {
        const logic = mountForm()
        logic.actions.setAlertFormValues({
            ...makeFormDefaults({
                threshold: {
                    configuration: {
                        type: InsightThresholdType.ABSOLUTE,
                        bounds: {},
                    },
                },
            }),
            checks: undefined,
        })

        expect(thresholdAlertHasBounds(logic.values.alertForm)).toBe(false)

        logic.actions.setAlertFormSubmitAttempted()

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(createSpy).not.toHaveBeenCalled()
        expect(successToastSpy).not.toHaveBeenCalled()
        expect(logic.values.thresholdBoundsFormError).toBe('Enter at least one threshold (less than or more than)')
    })

    it('treats cleared threshold inputs as missing bounds', () => {
        expect(
            thresholdAlertHasBounds({
                ...makeFormDefaults(),
                threshold: {
                    configuration: {
                        type: InsightThresholdType.ABSOLUTE,
                        bounds: { lower: '' as unknown as number, upper: '' as unknown as number },
                    },
                },
            })
        ).toBe(false)
    })

    it('blocks save with error toast for 15-minute interval without entitlement', async () => {
        userLogic.mount()
        upgradeModalLogic.mount()
        const logic = mountForm()
        logic.actions.setAlertFormValues({
            ...makeFormDefaults(),
            calculation_interval: AlertCalculationInterval.EVERY_15_MINUTES,
            checks: undefined,
        })

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(createSpy).not.toHaveBeenCalled()
        expect(upgradeModalLogic.values.upgradeModalFeatureKey).toBeNull()
        expect(errorToastSpy).toHaveBeenCalledWith(
            '15-minute alert intervals require a Boost, Scale, or Enterprise platform add-on.'
        )
        expect(successToastSpy).not.toHaveBeenCalled()
    })

    describe('hogql column prefill', () => {
        function mountHogqlForm(configOverrides: Record<string, any>): ReturnType<typeof alertFormLogic.build> {
            const logic = alertFormLogic({
                alert: null,
                insightId: 42,
                onEditSuccess: jest.fn(),
                insightVizDataLogicProps: insightLogicProps,
                insightInterval: 'day',
                insightAlertKind: 'hogql',
            })
            logic.mount()
            logic.actions.setAlertFormValue('config', {
                type: 'HogQLAlertConfig',
                evaluation: 'last_row',
                ...configOverrides,
            })
            return logic
        }

        it.each([
            {
                name: 'prefills the value column and the first non-evaluated column as label (last-row mode)',
                config: {},
                insightData: {
                    columns: ['day', 'count'],
                    results: [
                        ['2026-06-01', 1],
                        ['2026-06-02', 2],
                    ],
                },
                expectedColumn: 'count',
                expectedLabelColumn: 'day',
            },
            {
                name: 'keeps an explicit pick and labels by the other column',
                config: { column: 'a' },
                insightData: { columns: ['a', 'b'], results: [[1, 2]] },
                expectedColumn: 'a',
                expectedLabelColumn: 'b',
            },
            {
                name: 'prefills the last numeric column when several are numeric',
                config: {},
                insightData: { columns: ['a', 'b'], results: [[1, 2]] },
                expectedColumn: 'b',
                expectedLabelColumn: 'a',
            },
            {
                name: 'skips a trailing non-numeric column when picking the last numeric one',
                config: {},
                insightData: { columns: ['value', 'day'], results: [[5, '2026-06-01']] },
                expectedColumn: 'value',
                expectedLabelColumn: 'day',
            },
            {
                name: 'does not prefill when no column is numeric',
                config: {},
                insightData: { columns: ['a', 'b'], results: [['x', 'y']] },
                expectedColumn: undefined,
                expectedLabelColumn: undefined,
            },
            {
                name: 'does not prefill single-column results (picker hidden, auto keeps working on rename)',
                config: {},
                insightData: { columns: ['count'], results: [[5]] },
                expectedColumn: undefined,
                expectedLabelColumn: undefined,
            },
            {
                name: 'prefills the first non-evaluated column as the label in any-row mode',
                config: { evaluation: 'any_row' },
                insightData: { columns: ['day', 'count'], results: [['2026-06-01', 1]] },
                expectedColumn: 'count',
                expectedLabelColumn: 'day',
            },
            {
                name: 'prefills the label in first-row mode too (all modes unified)',
                config: { evaluation: 'first_row' },
                insightData: { columns: ['day', 'count'], results: [['2026-06-01', 1]] },
                expectedColumn: 'count',
                expectedLabelColumn: 'day',
            },
            {
                name: 'keeps an explicit label pick',
                config: { evaluation: 'any_row', label_column: 'a' },
                insightData: { columns: ['day', 'a', 'b'], results: [['2026-06-01', 1, 2]] },
                expectedColumn: 'b',
                expectedLabelColumn: 'a',
            },
        ])('$name', async ({ config, insightData, expectedColumn, expectedLabelColumn }) => {
            const logic = mountHogqlForm(config)
            insightDataLogic(insightLogicProps).actions.setInsightData(insightData)
            await expectLogic(logic).toFinishAllListeners()
            const formConfig = logic.values.alertForm.config as HogQLAlertConfig
            expect(formConfig.column).toEqual(expectedColumn)
            expect(formConfig.label_column).toEqual(expectedLabelColumn)
        })

        it('does not prefill when editing an existing alert (would dirty the form / clobber a saved column)', async () => {
            const logic = alertFormLogic({
                alert: makeSavedAlert({ config: { type: 'HogQLAlertConfig' } as any }),
                insightId: 42,
                onEditSuccess: jest.fn(),
                insightVizDataLogicProps: insightLogicProps,
                insightInterval: 'day',
                insightAlertKind: 'hogql',
            })
            logic.mount()
            insightDataLogic(insightLogicProps).actions.setInsightData({
                columns: ['day', 'count'],
                results: [['x', 1]],
            })
            await expectLogic(logic).toFinishAllListeners()
            const formConfig = logic.values.alertForm.config as HogQLAlertConfig
            expect(formConfig.column).toBeUndefined()
            expect(logic.values.alertFormChanged).toBe(false)
        })
    })

    describe('hogql column options', () => {
        function mountWithData(insightData: Record<string, any>): ReturnType<typeof alertFormLogic.build> {
            const logic = alertFormLogic({
                alert: null,
                insightId: 42,
                onEditSuccess: jest.fn(),
                insightVizDataLogicProps: insightLogicProps,
                insightInterval: 'day',
                insightAlertKind: 'hogql',
            })
            logic.mount()
            logic.actions.setAlertFormValue('config', { type: 'HogQLAlertConfig', evaluation: 'last_row' })
            insightDataLogic(insightLogicProps).actions.setInsightData(insightData)
            return logic
        }

        it('value options are the numeric columns only', () => {
            const logic = mountWithData({ columns: ['day', 'count'], results: [['2026-06-01', 1]] })
            expect(logic.values.hogqlValueColumnOptions).toEqual([{ label: 'count', value: 'count' }])
        })

        it('value options fall back to every column when nothing is numeric (avoids a dead-end picker)', () => {
            const logic = mountWithData({ columns: ['a', 'b'], results: [['x', 'y']] })
            expect(logic.values.hogqlValueColumnOptions).toEqual([
                { label: 'a', value: 'a' },
                { label: 'b', value: 'b' },
            ])
        })

        it('label options exclude the evaluated column', async () => {
            const logic = mountWithData({ columns: ['day', 'count'], results: [['2026-06-01', 1]] })
            // Wait for the prefill to materialize the evaluated column, then it should drop out of the label options.
            await expectLogic(logic).toFinishAllListeners()
            expect((logic.values.alertForm.config as HogQLAlertConfig).column).toEqual('count')
            expect(logic.values.hogqlLabelColumnOptions).toEqual([{ label: 'day', value: 'day' }])
        })
    })

    describe('deriveHogQLAlertPreview', () => {
        const HOGQL_CONFIG = { type: 'HogQLAlertConfig' } as const
        const ANY_ROW_CONFIG = { type: 'HogQLAlertConfig', evaluation: 'any_row' } as const
        const ok = (overrides: Record<string, any>): Record<string, any> => ({
            status: 'ok',
            mode: 'last_row',
            columnName: null,
            labelColumnName: null,
            currentValue: 0,
            previousValue: null,
            rowCount: 1,
            breachingRows: null,
            rows: expect.any(Array),
            ...overrides,
        })

        it.each([
            ['no result loaded', null, HOGQL_CONFIG, null, null],
            ['result not an array', { result: 'oops' }, HOGQL_CONFIG, null, null],
            ['empty result', { result: [] }, HOGQL_CONFIG, null, { status: 'no-rows' }],
            ['rows are not arrays', { result: [{ a: 1 }] }, HOGQL_CONFIG, null, { status: 'bad-shape' }],
            [
                'date column is skipped by the numeric heuristic',
                {
                    result: [
                        ['2024-01-01', 5],
                        ['2024-01-02', 7],
                    ],
                    columns: ['day', 'count'],
                },
                HOGQL_CONFIG,
                null,
                ok({
                    columnName: 'count',
                    labelColumnName: 'day',
                    currentValue: 7,
                    previousValue: 5,
                    rowCount: 2,
                    rows: [
                        { label: '2024-01-01', value: 5, breaching: false },
                        { label: '2024-01-02', value: 7, breaching: false },
                    ],
                }),
            ],
            [
                'two numeric columns are ambiguous',
                { result: [[1, 2]], columns: ['a', 'b'] },
                HOGQL_CONFIG,
                null,
                { status: 'ambiguous-columns', columnNames: ['a', 'b'] },
            ],
            [
                'explicit column pick',
                { result: [[1, 2]], columns: ['a', 'b'] },
                { type: 'HogQLAlertConfig', column: 'b' },
                null,
                ok({ columnName: 'b', labelColumnName: 'a', currentValue: 2 }),
            ],
            [
                'explicit column missing from result',
                { result: [[1]], columns: ['a'] },
                { type: 'HogQLAlertConfig', column: 'gone' },
                null,
                { status: 'missing-column', column: 'gone', columnNames: ['a'] },
            ],
            [
                'non-numeric value',
                { result: [['n/a']], columns: ['count'] },
                HOGQL_CONFIG,
                null,
                { status: 'not-numeric', value: 'n/a' },
            ],
            [
                'non-finite value',
                { result: [[Infinity]], columns: ['count'] },
                HOGQL_CONFIG,
                null,
                { status: 'not-numeric', value: 'Infinity' },
            ],
            [
                'null bucket evaluates as 0',
                { result: [[null]], columns: ['count'] },
                HOGQL_CONFIG,
                null,
                ok({ columnName: 'count', currentValue: 0 }),
            ],
            [
                'multiple rows expose previous value',
                { result: [[3], [7]], columns: ['count'] },
                HOGQL_CONFIG,
                null,
                ok({ columnName: 'count', currentValue: 7, previousValue: 3, rowCount: 2 }),
            ],
            [
                'backtest counts breaching rows against bounds',
                { result: [[3], [7], [12]], columns: ['count'] },
                HOGQL_CONFIG,
                { upper: 10 },
                ok({ columnName: 'count', currentValue: 12, previousValue: 7, rowCount: 3, breachingRows: 1 }),
            ],
            [
                'boolean value is not numeric',
                { result: [[true]], columns: ['flag'] },
                HOGQL_CONFIG,
                null,
                { status: 'not-numeric', value: 'true' },
            ],
            [
                'null cell evaluates as 0 and can breach in any-row mode',
                { result: [['US', null]], columns: ['country', 'count'] },
                // The all-null column defeats the numeric heuristic, so pick it explicitly.
                { type: 'HogQLAlertConfig', evaluation: 'any_row', column: 'count' },
                { upper: -1 },
                ok({
                    mode: 'any_row',
                    columnName: 'count',
                    labelColumnName: 'country',
                    currentValue: 0,
                    previousValue: null,
                    rowCount: 1,
                    breachingRows: 1,
                    rows: [{ label: 'US', value: 0, breaching: true }],
                }),
            ],
            [
                'any-row over the row cap',
                {
                    result: Array.from({ length: HOGQL_ANY_ROW_MAX_ROWS + 1 }, (_, i) => [i]),
                    columns: ['count'],
                },
                { type: 'HogQLAlertConfig', evaluation: 'any_row' },
                null,
                { status: 'too-many-rows', rowCount: HOGQL_ANY_ROW_MAX_ROWS + 1 },
            ],
            [
                'last-row at the truncation cap warns (tail may be truncated)',
                {
                    result: Array.from({ length: HOGQL_LAST_ROW_MAX_ROWS }, (_, i) => [i]),
                    columns: ['count'],
                },
                { type: 'HogQLAlertConfig', evaluation: 'last_row' },
                null,
                { status: 'last-row-truncated', rowCount: HOGQL_LAST_ROW_MAX_ROWS },
            ],
            [
                'missing explicit label column',
                { result: [['US', 1]], columns: ['country', 'count'] },
                { type: 'HogQLAlertConfig', evaluation: 'any_row', label_column: 'gone' },
                null,
                { status: 'missing-column', column: 'gone', columnNames: ['country', 'count'] },
            ],
            [
                'single column rows label by row number',
                { result: [[5], [50]], columns: ['count'] },
                { type: 'HogQLAlertConfig', evaluation: 'any_row' },
                { upper: 10 },
                ok({
                    mode: 'any_row',
                    columnName: 'count',
                    currentValue: 50,
                    previousValue: 5,
                    rowCount: 2,
                    breachingRows: 1,
                    rows: [
                        { label: 'row 1', value: 5, breaching: false },
                        { label: 'row 2', value: 50, breaching: true },
                    ],
                }),
            ],
            [
                'any-row mode reports breaching rows',
                {
                    result: [
                        ['US', 0.1],
                        ['DE', 0.4],
                    ],
                    columns: ['country', 'error_rate'],
                },
                ANY_ROW_CONFIG,
                { upper: 0.25 },
                ok({
                    mode: 'any_row',
                    columnName: 'error_rate',
                    labelColumnName: 'country',
                    currentValue: 0.4,
                    previousValue: 0.1,
                    rowCount: 2,
                    breachingRows: 1,
                    rows: [
                        { label: 'US', value: 0.1, breaching: false },
                        { label: 'DE', value: 0.4, breaching: true },
                    ],
                }),
            ],
        ])('%s', (_name, insightData, config, bounds, expected) => {
            expect(
                deriveHogQLAlertPreview(insightData as Record<string, any> | null, config as any, bounds as any)
            ).toEqual(expected)
        })

        it('first_row is immune to the last_row truncation cap (reads the head)', () => {
            const result = Array.from({ length: HOGQL_LAST_ROW_MAX_ROWS }, (_, i) => [i])
            const preview = deriveHogQLAlertPreview(
                { result, columns: ['count'] },
                { type: 'HogQLAlertConfig', evaluation: 'first_row' } as any,
                null
            )
            expect(preview?.status).toBe('ok')
        })
    })
})
