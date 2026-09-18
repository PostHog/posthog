import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    BILLING_USAGE_QUERY_TOO_LARGE_CODE,
    BillingUsageResponse,
    BillingUsageResponseBreakdownType,
    convertDesktopUsageSeries,
    getBillingUsageError,
    billingUsageLogic,
} from './billingUsageLogic'
import type { BillingFilters } from './types'

const series = (label: string, usageType: string, data: number[]): BillingUsageResponse['results'][number] => ({
    id: 1,
    label,
    data,
    dates: ['2026-08-01'],
    breakdown_type: BillingUsageResponseBreakdownType.TYPE,
    breakdown_value: usageType,
})

describe('convertDesktopUsageSeries', () => {
    it.each([
        [
            'PostHog Desktop token credits',
            'posthog_code_token_credits_used_in_period',
            1234,
            12.34,
            'PostHog Desktop token spend (USD)',
        ],
        ['Sandbox compute credits', 'sandbox_compute_credits_used_in_period', 266, 2.66, 'Cloud compute spend (USD)'],
        [
            'Sandbox compute CPU millicore-seconds',
            'sandbox_compute_cpu_millicore_seconds_in_period',
            1500,
            1.5,
            'Cloud compute CPU (core-seconds)',
        ],
        [
            'Sandbox compute memory MiB-seconds',
            'sandbox_compute_memory_mib_seconds_in_period',
            4608,
            4.5,
            'Cloud compute memory (GiB-seconds)',
        ],
    ])('converts %s without changing missing points', (label, usageType, input, output, expectedLabel) => {
        expect(convertDesktopUsageSeries(series(label, usageType, [input]))).toMatchObject({
            label: expectedLabel,
            data: [output],
        })
    })

    it('leaves unrelated usage series unchanged', () => {
        const input = series('Events', 'events', [10])
        expect(convertDesktopUsageSeries(input)).toBe(input)
    })

    it('converts a project breakdown and preserves its label', () => {
        const input = {
            ...series('my-project::PostHog Desktop token credits', 'posthog_code_token_credits_used_in_period', [1234]),
            breakdown_type: BillingUsageResponseBreakdownType.MULTIPLE,
            breakdown_value: ['posthog_code_token_credits_used_in_period', 'my-project'],
        }

        expect(convertDesktopUsageSeries(input)).toMatchObject({
            label: 'my-project::PostHog Desktop token spend (USD)',
            data: [12.34],
        })
    })
})

describe('getBillingUsageError', () => {
    it('preserves the actionable query-size error', () => {
        expect(
            getBillingUsageError({
                code: BILLING_USAGE_QUERY_TOO_LARGE_CODE,
                detail: 'Select a product.',
            })
        ).toEqual({
            code: BILLING_USAGE_QUERY_TOO_LARGE_CODE,
            detail: 'Select a product.',
        })
    })

    it('ignores errors without the expected API shape', () => {
        expect(getBillingUsageError(new Error('request failed'))).toBeNull()
        expect(getBillingUsageError({ code: BILLING_USAGE_QUERY_TOO_LARGE_CODE })).toBeNull()
    })
})

describe('billingUsageLogic loader', () => {
    let logic: ReturnType<typeof billingUsageLogic.build>
    let toastErrorSpy: jest.SpyInstance

    it('loads the project options on mount, apart from the chart', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': () => [200, { status: 'ok', type: 'timeseries', customer_id: 'c', results: [] }],
                '/api/billing/usage/team_options/': () => [200, { team_id_options: [3, 17] }],
            },
        })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingUsageLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadTeamIdOptions', 'loadTeamIdOptionsSuccess'])
            .toFinishAllListeners()

        expect(logic.values.teamIdOptions).toEqual([3, 17])
        expect(logic.values.teamIdOptionsLoading).toBe(false)
    })

    it('keeps an open-ended preset open, and asks for a range that ends yesterday', async () => {
        const endDates: string[] = []
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': ({ request }) => {
                    endDates.push(new URL(request.url).searchParams.get('end_date') ?? '')
                    return [200, { status: 'ok', type: 'timeseries', customer_id: 'c', results: [] }]
                },
            },
        })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingUsageLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setDateRange('yStart', null, false)
        await expectLogic(logic).toDispatchActions(['loadBillingUsageSuccess']).toFinishAllListeners()

        expect(logic.values.dateTo).toBeNull()
        expect(endDates[endDates.length - 1]).toEqual(dayjs().subtract(1, 'day').format('YYYY-MM-DD'))
    })

    beforeEach(() => {
        initKeaTests()
        toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
    })

    afterEach(() => {
        logic?.unmount()
        toastErrorSpy.mockRestore()
    })

    it('handles query-size errors without failing the loader', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': () => [
                    400,
                    { code: BILLING_USAGE_QUERY_TOO_LARGE_CODE, detail: 'Select a product.' },
                ],
            },
        })

        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

        logic = billingUsageLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadBillingUsageSuccess'])
            .toNotHaveDispatchedActions(['loadBillingUsageFailure'])
            .toFinishAllListeners()

        expect(logic.values.billingUsageError).toEqual({
            code: BILLING_USAGE_QUERY_TOO_LARGE_CODE,
            detail: 'Select a product.',
        })
        expect(toastErrorSpy).not.toHaveBeenCalled()
    })
})

describe('billingUsageLogic series toggling', () => {
    let logic: ReturnType<typeof billingUsageLogic.build>

    const row = (id: number, data: number[]): BillingUsageResponse['results'][number] => ({
        id,
        label: `Series ${id}`,
        data,
        dates: ['2026-08-01', '2026-08-02'],
        breakdown_type: BillingUsageResponseBreakdownType.TYPE,
        breakdown_value: `type_${id}`,
    })

    const mocksFor = (results: BillingUsageResponse['results']): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/billing': () => [200, billingJson],
            '/api/billing/usage/': () => [
                200,
                { status: 'ok', type: 'timeseries', customer_id: 'cus_1234', results } as BillingUsageResponse,
            ],
        },
    })

    const mount = async (): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

        logic = billingUsageLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingUsageSuccess']).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('hides every series with one action rather than one per series', async () => {
        useMocks(mocksFor([row(0, [1, 1]), row(1, [2, 2]), row(2, [3, 3])]))
        await mount()

        await expectLogic(logic, () => logic.actions.toggleAllSeries())
            .toDispatchActions(['setHiddenSeries'])
            .toNotHaveDispatchedActions(['toggleSeries'])
            .toFinishAllListeners()

        expect(logic.values.userHiddenSeries).toEqual([0, 1, 2])
    })

    it('shows every series again on the second press', async () => {
        useMocks(mocksFor([row(0, [1, 1]), row(1, [2, 2]), row(2, [3, 3])]))
        await mount()

        logic.actions.toggleAllSeries()
        await expectLogic(logic, () => logic.actions.toggleAllSeries())
            .toNotHaveDispatchedActions(['toggleSeries'])
            .toFinishAllListeners()

        expect(logic.values.userHiddenSeries).toEqual([])
    })

    it('keeps a hidden series hidden when it sits outside the set being toggled', async () => {
        // Series 0 is empty, so "exclude empty" drops it from the set the header checkbox acts on.
        // Hiding all must not quietly bring it back: the new hidden list is the union of what the
        // user had hidden and what was just hidden, not a replacement.
        useMocks(mocksFor([row(0, [0, 0]), row(1, [2, 2]), row(2, [3, 3])]))
        await mount()

        logic.actions.setExcludeEmptySeries(true)
        logic.actions.toggleSeries(0)
        expect(logic.values.userHiddenSeries).toEqual([0])

        logic.actions.toggleAllSeries()

        expect(logic.values.userHiddenSeries).toEqual([0, 1, 2])
    })
})

describe('billingUsageLogic chart type', () => {
    let logic: ReturnType<typeof billingUsageLogic.build>

    // useMocks has to be called straight from the test body: the hooks lint rule rejects a
    // hook-named call inside an ordinary helper.
    const mocks = (): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/billing': () => [200, billingJson],
            '/api/billing/usage/': () => [
                200,
                { status: 'ok', type: 'timeseries', customer_id: 'cus_1234', results: [] },
            ],
        },
    })

    const mount = async (): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingUsageLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingUsageSuccess']).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('will not stack usage types, because they are not the same unit', async () => {
        useMocks(mocks())
        await mount()

        logic.actions.setFilters({ usage_types: ['event_count_in_period', 'recording_count_in_period'] })

        expect(logic.values.canStackSeries).toBe(false)
    })

    it('will stack once a single product is selected', async () => {
        useMocks(mocks())
        await mount()

        logic.actions.setFilters({ usage_types: ['event_count_in_period'] })

        expect(logic.values.canStackSeries).toBe(true)
    })

    it('falls back to a line when bars are asked for but cannot be stacked', async () => {
        // A URL can name a chart type the data does not support, so the guard lives in the
        // selector as well as on the disabled control.
        useMocks(mocks())
        await mount()

        logic.actions.setFilters({ usage_types: ['event_count_in_period', 'recording_count_in_period'] })
        logic.actions.setChartType('bar')

        expect(logic.values.chartType).toBe('bar')
        expect(logic.values.effectiveChartType).toBe('line')
    })

    it('honours bars once the selection makes them meaningful', async () => {
        useMocks(mocks())
        await mount()

        logic.actions.setChartType('bar')
        logic.actions.setFilters({ usage_types: ['event_count_in_period'] })

        expect(logic.values.effectiveChartType).toBe('bar')
    })

    it('defaults to a line', async () => {
        useMocks(mocks())
        await mount()

        expect(logic.values.chartType).toBeNull()
        expect(logic.values.effectiveChartType).toBe('line')
    })
})

describe('billingUsageLogic project breakdown requests', () => {
    let logic: ReturnType<typeof billingUsageLogic.build>
    let requests: { types: string; page_size: string | null; after: string | null; top_projects: string | null }[]

    const empty = { status: 'ok', type: 'timeseries', customer_id: 'c', results: [] }

    const record = (request: Request): URLSearchParams => {
        const params = new URL(request.url).searchParams
        requests.push({
            types: params.get('usage_types') ?? 'all',
            page_size: params.get('page_size'),
            after: params.get('after'),
            top_projects: params.get('top_projects'),
        })
        return params
    }

    const seriesFor = (team: string): BillingUsageResponse['results'] => [
        {
            id: 0,
            label: `${team}::Events`,
            data: [1],
            dates: ['2026-08-01'],
            breakdown_type: BillingUsageResponseBreakdownType.MULTIPLE,
            breakdown_value: ['event_count_in_period', team],
        },
    ]

    const mount = async (initialFilters: BillingFilters): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingUsageLogic({ initialFilters })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingUsageSuccess']).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        requests = []
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('asks once, with the project cap, when top_projects bounds the answer', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': ({ request }) => {
                    record(request)
                    return [200, empty]
                },
            },
        })

        await mount({ breakdowns: ['type', 'team'], top_projects: 20 })

        expect(requests).toEqual([{ types: 'all', page_size: null, after: null, top_projects: '20' }])
    })

    it('asks for every project on every usage type in one request', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': ({ request }) => {
                    record(request)
                    return [200, { ...empty, results: seriesFor('1') }]
                },
            },
        })

        await mount({ breakdowns: ['type', 'team'], top_projects: null })

        expect(requests.map((r) => [r.types, r.page_size])).toEqual([['all', null]])
        const ids = logic.values.series.map((s) => s.id)
        expect(new Set(ids).size).toBe(ids.length)
    })

    it('sends one request when there is no project breakdown', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': ({ request }) => {
                    record(request)
                    return [200, empty]
                },
            },
        })

        await mount({ breakdowns: ['type'] })

        expect(requests.length).toBe(1)
    })
})

describe('billing section URL scoping', () => {
    let logic: ReturnType<typeof billingUsageLogic.build>
    let usageRequests: number

    beforeEach(() => {
        initKeaTests()
        usageRequests = 0
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/usage/': () => {
                    usageRequests += 1
                    return [200, { status: 'ok', type: 'timeseries', customer_id: 'c', results: [] }]
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The two pages write the same query parameter names, so a logic listening on '*' would
    // read the spend page's filter changes as its own and refetch against them.
    it('ignores filter changes made on the spend page', async () => {
        router.actions.push(urls.organizationBillingSection('usage'))
        logic = billingUsageLogic({ syncWithUrl: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const afterMount = usageRequests

        router.actions.push(urls.organizationBillingSection('spend'), {
            breakdowns: ['type', 'team'],
            usage_types: ['event_count_in_period'],
            date_from: '2026-01-01',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(usageRequests).toEqual(afterMount)
    })

    it('still follows filter changes made on its own page', async () => {
        router.actions.push(urls.organizationBillingSection('usage'))
        logic = billingUsageLogic({ syncWithUrl: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const afterMount = usageRequests

        router.actions.push(urls.organizationBillingSection('usage'), { date_from: '2026-01-01' })
        await expectLogic(logic).toFinishAllListeners()

        expect(usageRequests).toBeGreaterThan(afterMount)
    })
})

describe('billingUsageLogic export', () => {
    let logic: ReturnType<typeof billingUsageLogic.build>

    // useMocks has to be called from the test body: the hooks lint rule rejects it in a helper.
    const mocks = (): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/billing': () => [200, billingJson],
            '/api/billing/usage/': () => [200, { status: 'ok', type: 'timeseries', customer_id: 'c', results: [] }],
        },
    })

    const mount = async (initialFilters: BillingFilters): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingUsageLogic({ initialFilters })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingUsageSuccess']).toFinishAllListeners()
    }

    const params = (url: string): URLSearchParams => new URL(url, 'http://localhost').searchParams

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('exports every project without the chart cap, and the chart series with it', async () => {
        useMocks(mocks())
        await mount({ breakdowns: ['type', 'team'], top_projects: 20, interval: 'day' })

        const every = params(logic.values.usageExportUrl)
        expect(every.get('top_projects')).toBeNull()
        expect(every.get('breakdowns')).toBe('["type","team"]')
        expect(params(logic.values.usageChartExportUrl).get('top_projects')).toBe('20')
    })
})
