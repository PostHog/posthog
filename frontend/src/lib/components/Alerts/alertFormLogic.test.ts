import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    InsightThresholdType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { alertFormLogic, type AlertFormType } from './alertFormLogic'
import { alertNotificationLogic } from './alertNotificationLogic'
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
        jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [] })
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
            historyChartEnabled: false,
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
            historyChartEnabled: false,
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
})
