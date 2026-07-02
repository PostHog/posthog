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
    ForecastConditionType,
    ForecastEngineType,
    HogQLAlertConfig,
    InsightThresholdType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import {
    alertFormLogic,
    canCheckOngoingInterval,
    ongoingIntervalField,
    thresholdAlertHasBounds,
    type AlertFormType,
} from './alertFormLogic'
import { alertNotificationLogic } from './alertNotificationLogic'
import { deriveFunnelAlertPreview } from './funnelAlertPreview'
import { deriveHogQLAlertPreview, HOGQL_ANY_ROW_MAX_ROWS, HOGQL_LAST_ROW_MAX_ROWS } from './hogqlAlertPreview'
import { insightAlertsLogic } from './insightAlertsLogic'
import { supportsOngoingInterval } from './types'
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

    // Funnels hide the #/% unit toggle and always compare a relative change as a percentage of the
    // prior period, so a funnel relative alert must persist with a PERCENTAGE threshold even if the
    // form still carries an ABSOLUTE type. Regresses if the submit-side force is dropped.
    it('persists a funnel relative alert with a PERCENTAGE threshold', async () => {
        const logic = mountForm()
        logic.actions.setAlertFormValues({
            ...makeFormDefaults({
                config: { type: 'FunnelsAlertConfig', metric: 'conversion_from_start', funnel_step: null },
                condition: { type: AlertConditionType.RELATIVE_DECREASE },
                threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: { lower: 0.2 } } },
            }),
            checks: undefined,
        })

        await expectLogic(logic, () => {
            logic.actions.submitAlertForm()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        expect(createSpy.mock.calls[0][0].threshold.configuration.type).toBe(InsightThresholdType.PERCENTAGE)
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

    it('switching to forecast mode sets a default forecast_config and clears detector_config', () => {
        const logic = mountForm()
        logic.actions.setAlertFormValue('detector_config', { type: 'zscore' })
        logic.actions.setAlertFormValue('forecast_config', {
            type: 'ForecastConfig',
            engine: ForecastEngineType.PROPHET,
            condition: ForecastConditionType.FUTURE_BREACH,
            horizon: 7,
            interval_width: 0.95,
        })
        logic.actions.setAlertFormValue('detector_config', null)
        expect(logic.values.alertForm.forecast_config?.condition).toBe('future_breach')
        expect(logic.values.alertForm.detector_config).toBeNull()
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

    describe('deriveFunnelAlertPreview', () => {
        const FROM_START = { type: 'FunnelsAlertConfig', metric: 'conversion_from_start', funnel_step: null } as const
        const steps = (...counts: number[]): Record<string, any>[] =>
            counts.map((count, order) => ({ order, count, breakdown_value: null }))
        const value = (label: string | null, rate: number, breaching: boolean): Record<string, any> => ({
            label,
            rate,
            breaching,
        })

        it.each([
            ['not a funnel config', { result: steps(100, 40) }, { type: 'HogQLAlertConfig' }, undefined, null],
            ['no result loaded', null, FROM_START, undefined, null],
            ['empty result', { result: [] }, FROM_START, undefined, null],
            ['breakdown with an empty step list', { result: [[]] }, FROM_START, undefined, { status: 'no-data' }],
            [
                'from_start at the last step, no bounds',
                { result: steps(100, 40) },
                FROM_START,
                undefined,
                { status: 'ok', values: [value(null, 40, false)], isBreakdown: false, hasBounds: false },
            ],
            [
                'lower bound breached flags the value and sets hasBounds',
                { result: steps(100, 40) },
                FROM_START,
                { lower: 50 },
                { status: 'ok', values: [value(null, 40, true)], isBreakdown: false, hasBounds: true },
            ],
            [
                'value within bounds is not breaching',
                { result: steps(100, 40) },
                FROM_START,
                { lower: 30 },
                { status: 'ok', values: [value(null, 40, false)], isBreakdown: false, hasBounds: true },
            ],
            [
                'upper bound breached flags the value',
                { result: steps(100, 40) },
                FROM_START,
                { upper: 30 },
                { status: 'ok', values: [value(null, 40, true)], isBreakdown: false, hasBounds: true },
            ],
            [
                'within a lower+upper range is not breaching',
                { result: steps(100, 40) },
                FROM_START,
                { lower: 10, upper: 80 },
                { status: 'ok', values: [value(null, 40, false)], isBreakdown: false, hasBounds: true },
            ],
            [
                'breaching the upper of a lower+upper range flags the value',
                { result: steps(100, 40) },
                FROM_START,
                { lower: 10, upper: 30 },
                { status: 'ok', values: [value(null, 40, true)], isBreakdown: false, hasBounds: true },
            ],
            [
                'from_previous divides by the prior step',
                { result: steps(100, 50, 10) },
                { type: 'FunnelsAlertConfig', metric: 'conversion_from_previous', funnel_step: 2 },
                undefined,
                { status: 'ok', values: [value(null, 20, false)], isBreakdown: false, hasBounds: false },
            ],
            [
                'zero base evaluates to 0%',
                { result: steps(0, 5) },
                FROM_START,
                undefined,
                { status: 'ok', values: [value(null, 0, false)], isBreakdown: false, hasBounds: false },
            ],
            [
                'breakdown computes a rate per value and flags only the breaching one',
                {
                    result: [
                        [
                            { order: 0, count: 100, breakdown_value: 'US' },
                            { order: 1, count: 40, breakdown_value: 'US' },
                        ],
                        [
                            { order: 0, count: 80, breakdown_value: 'DE' },
                            { order: 1, count: 20, breakdown_value: 'DE' },
                        ],
                    ],
                },
                FROM_START,
                { lower: 30 },
                {
                    status: 'ok',
                    values: [value('US', 40, false), value('DE', 25, true)],
                    isBreakdown: true,
                    hasBounds: true,
                },
            ],
            [
                'compared funnel evaluates the current period only',
                {
                    result: [
                        { order: 0, count: 1000, compare_label: 'current', breakdown_value: null },
                        { order: 1, count: 100, compare_label: 'current', breakdown_value: null },
                        { order: 0, count: 800, compare_label: 'previous', breakdown_value: null },
                        { order: 1, count: 120, compare_label: 'previous', breakdown_value: null },
                    ],
                },
                FROM_START,
                undefined,
                { status: 'ok', values: [value(null, 10, false)], isBreakdown: false, hasBounds: false },
            ],
            [
                'compared funnel with only previous-period rows shows no-data, not unloaded',
                {
                    result: [
                        { order: 0, count: 800, compare_label: 'previous', breakdown_value: null },
                        { order: 1, count: 120, compare_label: 'previous', breakdown_value: null },
                    ],
                },
                FROM_START,
                undefined,
                { status: 'no-data' },
            ],
        ])('%s', (_name, insightData, config, bounds, expected) => {
            expect(
                deriveFunnelAlertPreview(insightData as Record<string, any> | null, config as any, bounds as any, false)
            ).toEqual(expected)
        })

        // Trends funnels return a conversion-rate time series; the alert evaluates the last complete
        // period by default, or the latest in-progress one when check_ongoing_interval is set.
        const trend = (data: (number | null)[], breakdown_value: unknown = null): Record<string, any> => ({
            data,
            days: data.map((_, i) => `d${i}`),
            breakdown_value,
        })
        const ongoing = { ...FROM_START, check_ongoing_interval: true } as const
        it.each([
            [
                'default evaluates the last complete period (the latest is in progress)',
                { result: [trend([10, 25, 40])] },
                FROM_START,
                { lower: 50 },
                undefined,
                undefined,
                { status: 'ok', values: [value(null, 25, true)], isBreakdown: false, hasBounds: true },
            ],
            [
                // Regression guard: the backend skips a null anchor, so the preview must not read it as a
                // breaching 0% against a lower bound.
                'a null anchor period is treated as no data, not a 0% breach',
                { result: [trend([null, 25])] },
                FROM_START,
                { lower: 50 },
                undefined,
                undefined,
                { status: 'ok', values: [value(null, 0, false)], isBreakdown: false, hasBounds: true },
            ],
            [
                'check_ongoing_interval evaluates the latest (in-progress) period',
                { result: [trend([10, 25, 40])] },
                ongoing,
                { lower: 30 },
                undefined,
                undefined,
                { status: 'ok', values: [value(null, 40, false)], isBreakdown: false, hasBounds: true },
            ],
            [
                'breakdown yields one value per series and drops previous-period rows',
                {
                    result: [
                        { ...trend([10, 40], ['Chrome']), compare_label: 'current' },
                        { ...trend([5, 20], ['Safari']), compare_label: 'current' },
                        { ...trend([8, 30], ['Chrome']), compare_label: 'previous' },
                    ],
                },
                FROM_START,
                { lower: 8 },
                undefined,
                undefined,
                {
                    status: 'ok',
                    values: [value('Chrome', 10, false), value('Safari', 5, true)],
                    isBreakdown: true,
                    hasBounds: true,
                },
            ],
            [
                // 5 is the in-progress period (skipped by default); compares 30 against 40 — a 10-point
                // drop, over the 8-point upper bound → breach.
                'relative decrease evaluates the last complete period vs the prior one',
                { result: [trend([40, 30, 5])] },
                FROM_START,
                { upper: 8 },
                AlertConditionType.RELATIVE_DECREASE,
                InsightThresholdType.ABSOLUTE,
                {
                    status: 'ok',
                    values: [{ label: null, rate: 30, previousRate: 40, breaching: true }],
                    isBreakdown: false,
                    hasBounds: true,
                    relative: true,
                },
            ],
            [
                // check_ongoing → anchor the latest period (5) against the prior one (30): a 25-point drop.
                'relative decrease with check_ongoing_interval diffs the in-progress period',
                { result: [trend([40, 30, 5])] },
                ongoing,
                { upper: 8 },
                AlertConditionType.RELATIVE_DECREASE,
                InsightThresholdType.ABSOLUTE,
                {
                    status: 'ok',
                    values: [{ label: null, rate: 5, previousRate: 30, breaching: true }],
                    isBreakdown: false,
                    hasBounds: true,
                    relative: true,
                },
            ],
            [
                // 60 → 40 is a 33% relative drop; percentage bounds are a ratio (0.3), so 0.333 breaches —
                // mirroring the backend comparator's _relative_value.
                'relative decrease with a percentage threshold compares the ratio change',
                { result: [trend([60, 40])] },
                ongoing,
                { upper: 0.3 },
                AlertConditionType.RELATIVE_DECREASE,
                InsightThresholdType.PERCENTAGE,
                {
                    status: 'ok',
                    values: [{ label: null, rate: 40, previousRate: 60, breaching: true }],
                    isBreakdown: false,
                    hasBounds: true,
                    relative: true,
                },
            ],
            [
                'relative with only one complete period flags no prior',
                { result: [trend([30, 20])] }, // 20 is in progress; only one complete period
                FROM_START,
                { upper: 5 },
                AlertConditionType.RELATIVE_DECREASE,
                InsightThresholdType.ABSOLUTE,
                {
                    status: 'ok',
                    values: [{ label: null, rate: 30, breaching: false }],
                    isBreakdown: false,
                    hasBounds: true,
                    relative: true,
                },
            ],
        ])('trends funnel: %s', (_name, insightData, config, bounds, conditionType, thresholdType, expected) => {
            expect(
                deriveFunnelAlertPreview(
                    insightData as Record<string, any> | null,
                    config as any,
                    bounds as any,
                    true,
                    conditionType as any,
                    thresholdType as any
                )
            ).toEqual(expected)
        })
    })

    describe('ongoing-interval gating', () => {
        const funnelConfig = { type: 'FunnelsAlertConfig', metric: 'conversion_from_start', funnel_step: null }
        const trendsAbsoluteWithUpper = (condition: AlertConditionType): any => ({
            condition: { type: condition },
            threshold: { configuration: { bounds: { upper: 10 } } },
        })

        // supportsOngoingInterval is config-level: trends and funnels carry check_ongoing_interval; the
        // steps-vs-trends funnel gate lives in canCheckOngoingInterval below.
        it.each([
            ['trends config', { type: 'TrendsAlertConfig', series_index: 0 }, true],
            ['funnel config', funnelConfig, true],
            ['SQL config', { type: 'HogQLAlertConfig', evaluation: 'last_row' }, false],
            ['null', null, false],
        ])('supportsOngoingInterval(%s) === %s', (_name, config, expected) => {
            expect(supportsOngoingInterval(config as any)).toBe(expected)
        })

        it('canCheckOngoingInterval: a steps funnel cannot, a trends funnel can', () => {
            const funnelAlert: any = { config: funnelConfig, condition: { type: AlertConditionType.RELATIVE_DECREASE } }
            expect(canCheckOngoingInterval(funnelAlert, { isTrendsFunnel: false })).toBe(false)
            expect(canCheckOngoingInterval(funnelAlert, { isTrendsFunnel: true })).toBe(true)
        })

        it.each([
            ['absolute value with an upper bound', AlertConditionType.ABSOLUTE_VALUE, true],
            ['relative increase with an upper bound', AlertConditionType.RELATIVE_INCREASE, true],
            ['relative decrease (never)', AlertConditionType.RELATIVE_DECREASE, false],
        ])('canCheckOngoingInterval trends: %s → %s', (_name, condition, expected) => {
            expect(canCheckOngoingInterval(trendsAbsoluteWithUpper(condition))).toBe(expected)
        })

        it('canCheckOngoingInterval trends: absolute without an upper bound cannot', () => {
            const alert: any = {
                condition: { type: AlertConditionType.ABSOLUTE_VALUE },
                threshold: { configuration: { bounds: {} } },
            }
            expect(canCheckOngoingInterval(alert)).toBe(false)
        })

        // The util the advanced-options section renders from — one place for the per-kind branching.
        it.each([
            [
                'trends, eligible',
                { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: true },
                true,
                true,
                true,
                false,
            ],
            [
                'trends, ineligible (shown but disabled)',
                { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: true },
                false,
                true,
                false,
                true,
            ],
            ['steps funnel (canCheck false → hidden)', funnelConfig, false, false, false, true],
            ['trends funnel (canCheck true → shown, no reason)', funnelConfig, true, true, false, false],
            ['SQL (never shown)', { type: 'HogQLAlertConfig', evaluation: 'last_row' }, false, false, false, true],
        ])('ongoingIntervalField: %s', (_name, config, canCheck, show, checked, hasReason) => {
            const field = ongoingIntervalField(config as any, canCheck)
            expect(field.show).toBe(show)
            expect(field.checked).toBe(checked)
            expect(field.disabledReason !== undefined).toBe(hasReason)
            expect(field.tooltip.length).toBeGreaterThan(0)
        })
    })
})
