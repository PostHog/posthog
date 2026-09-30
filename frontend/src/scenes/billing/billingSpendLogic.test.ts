import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils/dateFilters'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BillingSpendResponse, BillingSpendResponseBreakdownType, billingSpendLogic } from './billingSpendLogic'
import { fitsOneRequest, isDayOrCoarser, SUB_DAY_DATE_FILTER_INTERVALS } from './billingUsageLogic'
import type { BillingFilters } from './types'

describe('billingSpendLogic chart type', () => {
    let logic: ReturnType<typeof billingSpendLogic.build>

    // useMocks has to be called straight from the test body: the hooks lint rule rejects a
    // hook-named call inside an ordinary helper.
    const mocks = (): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/billing': () => [200, billingJson],
            '/api/billing/spend/': () => [
                200,
                { status: 'ok', type: 'timeseries', customer_id: 'cus_1234', results: [] },
            ],
        },
    })

    const mount = async (): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingSpendLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingSpendSuccess']).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the project options on mount, apart from the chart', async () => {
        const base = mocks()
        useMocks({
            ...base,
            get: { ...base.get, '/api/billing/usage/team_options/': () => [200, { team_id_options: [3, 17] }] },
        })
        await mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.teamIdOptions).toEqual([3, 17])
        expect(logic.values.teamIdOptionsLoading).toBe(false)
    })

    it('always allows stacking, because spend is dollars in every breakdown', async () => {
        useMocks(mocks())
        await mount()

        expect(logic.values.canStackSeries).toBe(true)
    })

    it('defaults to stacked bars once the breakdown is by project', async () => {
        // A stacked bar shows the bill and the projects it is made of; a line shows neither, so the
        // default with a project breakdown is a bar.
        useMocks(mocks())
        await mount()

        logic.actions.setFilters({ breakdowns: ['type', 'team'] })

        expect(logic.values.effectiveChartType).toBe('bar')
    })

    it('defaults to a line without a project breakdown, where there is nothing to compose', async () => {
        useMocks(mocks())
        await mount()

        logic.actions.setFilters({ breakdowns: ['type'] })

        expect(logic.values.effectiveChartType).toBe('line')
    })

    it('keeps a chosen type when the breakdown changes the default underneath it', async () => {
        // The stored value is null until someone picks, so the default can follow the breakdown.
        // Once they pick, that choice outranks the default rather than being overwritten by it.
        useMocks(mocks())
        await mount()

        logic.actions.setChartType('line')
        logic.actions.setFilters({ breakdowns: ['type', 'team'] })

        expect(logic.values.effectiveChartType).toBe('line')
    })
})

describe('billingSpendLogic project breakdown requests', () => {
    let logic: ReturnType<typeof billingSpendLogic.build>
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

    const seriesFor = (team: string): BillingSpendResponse['results'] => [
        {
            id: 0,
            label: `${team}::Events`,
            data: [1],
            dates: ['2026-08-01'],
            breakdown_type: BillingSpendResponseBreakdownType.MULTIPLE,
            breakdown_value: ['product_analytics', team],
        },
    ]

    const mount = async (initialFilters: BillingFilters): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingSpendLogic({ initialFilters })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingSpendSuccess']).toFinishAllListeners()
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
                '/api/billing/spend/': ({ request }) => {
                    record(request)
                    return [200, empty]
                },
            },
        })

        await mount({ breakdowns: ['type', 'team'], top_projects: 20 })

        expect(requests).toEqual([{ types: 'all', page_size: null, after: null, top_projects: '20' }])
    })

    it('asks for every project on every product in one request', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/spend/': ({ request }) => {
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

    it('sends one request without a project breakdown', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/spend/': ({ request }) => {
                    record(request)
                    return [200, empty]
                },
            },
        })

        await mount({ breakdowns: ['type'] })

        expect(requests.length).toBe(1)
    })
})

describe('billing date options', () => {
    // "Last hour" reached the API as `start_date=-1h`, which is not a date, so billing read the
    // range as backwards and rejected the whole request with "start_date must be before or equal
    // to end_date". A filter that only excluded 'hour' intervals would let it through, because
    // "Last hour" is a 'minute' one.
    it('offers nothing finer than a day, whatever interval the option declares', () => {
        const subDay = dateMapping.filter(
            (option) => option.defaultInterval && SUB_DAY_DATE_FILTER_INTERVALS.includes(option.defaultInterval)
        )
        expect(subDay.length).toBeGreaterThan(0)
        expect(subDay.map((option) => option.key)).toContain('Last hour')
        expect(subDay.filter(isDayOrCoarser)).toEqual([])
    })

    it('keeps the day and month options', () => {
        const kept = dateMapping.filter(isDayOrCoarser).map((option) => option.key)
        expect(kept).toContain('Last 7 days')
        expect(kept).toContain('Last 30 days')
        expect(kept).not.toContain('Last hour')
        expect(kept).not.toContain('Last 24 hours')
    })

    it('does not offer All time, since billing serves at most a year per request', () => {
        const offered = dateMapping
            .filter(isDayOrCoarser)
            .filter(fitsOneRequest)
            .map((option) => option.key)
        expect(dateMapping.map((option) => option.key)).toContain('All time')
        expect(offered).not.toContain('All time')
        expect(offered).toContain('This year')
        expect(offered).toContain('Last 180 days')
    })
})

describe('billing spend load triggers', () => {
    let logic: ReturnType<typeof billingSpendLogic.build>
    let requests: number
    let startDates: string[]
    let endDates: string[]

    beforeEach(() => {
        initKeaTests()
        requests = 0
        startDates = []
        endDates = []
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/spend/': ({ request }) => {
                    requests += 1
                    const params = new URL(request.url).searchParams
                    startDates.push(params.get('start_date') ?? '')
                    endDates.push(params.get('end_date') ?? '')
                    return [200, { status: 'ok', type: 'timeseries', customer_id: 'c', results: [] }]
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // afterMount, urlToAction reading the filters out of the URL, and the subscriptions that
    // fire once billing says the plan is not hobby and the person may see spend all want to
    // load on arrival. Only one request may go out.
    it('loads once on arrival rather than once per trigger', async () => {
        router.actions.push(urls.organizationBillingSection('spend'), {
            breakdowns: ['type', 'team'],
            date_from: '2026-01-01',
        })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

        logic = billingSpendLogic({ syncWithUrl: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // One request.
        expect(requests).toEqual(1)
        // And it carries the dates from the URL, not the defaults the logic starts with.
        expect(new Set(startDates)).toEqual(new Set(['2026-01-01']))
    })

    it('keeps an open-ended preset open, and asks for a range that ends yesterday', async () => {
        // "This year" carries only a start. The picker recognises its own preset only while the
        // end stays empty; with yesterday filled in it would read back as "No date range override".
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingSpendLogic({})
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setDateRange('yStart', null, false)
        await expectLogic(logic).toDispatchActions(['loadBillingSpendSuccess']).toFinishAllListeners()

        expect(logic.values.dateFrom).toEqual('yStart')
        expect(logic.values.dateTo).toBeNull()
        expect(endDates[endDates.length - 1]).toEqual(dayjs().subtract(1, 'day').format('YYYY-MM-DD'))
    })
})

describe('billingSpendLogic export', () => {
    let logic: ReturnType<typeof billingSpendLogic.build>

    const days = (count: number): string[] =>
        Array.from({ length: count }, (_, i) => dayjs('2025-09-01').add(i, 'day').format('YYYY-MM-DD'))

    const response = (periods: number): BillingSpendResponse => ({
        status: 'ok',
        type: 'timeseries',
        customer_id: 'c',
        results: [
            {
                id: 0,
                label: '1::Events',
                data: days(periods).map(() => 1),
                dates: days(periods),
                breakdown_type: BillingSpendResponseBreakdownType.MULTIPLE,
                breakdown_value: ['product_analytics', '1'],
            },
        ],
    })

    // useMocks has to be called from the test body: the hooks lint rule rejects it in a helper.
    const mocks = (teams: number, periods: number): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/billing': () => [200, billingJson],
            '/api/billing/spend/': () => [200, response(periods)],
            '/api/billing/usage/team_options/': () => [
                200,
                { team_id_options: Array.from({ length: teams }, (_, i) => i + 1) },
            ],
        },
    })

    const mount = async (initialFilters: BillingFilters): Promise<void> => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        logic = billingSpendLogic({ initialFilters })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBillingSpendSuccess']).toFinishAllListeners()
    }

    const params = (url: string): URLSearchParams => new URL(url, 'http://localhost').searchParams

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('exports every project without the chart cap, and the chart series with it', async () => {
        useMocks(mocks(3, 2))
        await mount({ breakdowns: ['type', 'team'], top_projects: 20, interval: 'day' })

        const every = params(logic.values.spendExportUrl)
        expect(every.get('top_projects')).toBeNull()
        expect(every.get('breakdowns')).toBe('["type","team"]')
        expect(every.get('interval')).toBe('day')
        expect(params(logic.values.spendChartExportUrl).get('top_projects')).toBe('20')
    })
})
