import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { buildAiObservabilityStorageConfig } from '../shared/preferenceStorage'
import { pageLoad } from '../shared/testPageLoad'
import { rawSearchParam } from '../trace/rawSearchParam'
import { shellScopeLogic } from './shellScopeLogic'

const TRACES = urls.aiObservabilityTraces()
const STORAGE_KEY = 'ai_observability.shell_date_range'

describe('shellScopeLogic', () => {
    let logic: ReturnType<typeof shellScopeLogic.build>

    function mountAt(url: string): void {
        router.actions.locationChanged(pageLoad(url))
        logic = shellScopeLogic()
        logic.mount()
    }

    function rememberPick(dateFrom: string): void {
        mountAt(TRACES)
        logic.actions.setDateRange(dateFrom, null)
        logic.unmount()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts on the last seven days', () => {
        mountAt(TRACES)

        expect(logic.values).toMatchObject({ dateFrom: '-7d', dateTo: null })
    })

    it('takes the range in the url over the remembered pick', () => {
        rememberPick('-30d')

        mountAt(`${TRACES}?date_from=-24h&date_to=-1h`)

        expect(logic.values).toMatchObject({ dateFrom: '-24h', dateTo: '-1h' })
    })

    it('opens on the remembered pick when the url has no range', () => {
        rememberPick('-30d')

        mountAt(urls.aiObservabilityErrors())

        expect(logic.values.dateFrom).toEqual('-30d')
    })

    it('neither applies nor remembers a date that does not parse', () => {
        rememberPick('-30d')

        mountAt(`${TRACES}?date_from=garbage`)
        expect(logic.values.dateFrom).toEqual('-30d')
        logic.unmount()

        mountAt(TRACES)
        expect(logic.values.dateFrom).toEqual('-30d')
    })

    it('ignores the range of a page outside the shell and leaves its url alone', () => {
        rememberPick('-30d')
        mountAt(TRACES)
        const outside = `${urls.webAnalytics()}?date_from=-90d&date_to=-1d`
        const remembered = localStorage.getItem(STORAGE_KEY)

        router.actions.push(outside)

        expect(logic.values).toMatchObject({ dateFrom: '-30d', dateTo: null })
        expect(localStorage.getItem(STORAGE_KEY)).toEqual(remembered)
        expect(router.values.lastMethod).toEqual('PUSH')
        expect(router.values.searchParams).toEqual({ date_from: '-90d', date_to: '-1d' })
    })

    it.each(['1.50', '{"answer": 1}'])(
        'writes the range to the url in place and keeps the other params as typed, with search %s',
        (search) => {
            mountAt(
                `${TRACES}?date_from=-24h&date_to=-1h&trace_search=${encodeURIComponent(search)}&filters=${encodeURIComponent('[{"key":"model"}]')}`
            )

            logic.actions.setDateRange('-1h', null)

            expect(router.values.location.pathname).toContain(TRACES)
            expect({
                ...router.values.searchParams,
                trace_search: rawSearchParam(router.values.location.search, 'trace_search'),
            }).toEqual({
                date_from: '-1h',
                trace_search: search,
                filters: [{ key: 'model' }],
            })
            expect(router.values.lastMethod).toEqual('REPLACE')
        }
    )

    describe('filterTestAccounts', () => {
        it.each([true, false])('defaults filterTestAccounts to the project default %s', (projectDefault) => {
            filterTestAccountsDefaultsLogic.mount()
            filterTestAccountsDefaultsLogic.actions.setLocalDefault(projectDefault)

            mountAt(TRACES)

            expect(logic.values.filterTestAccounts).toBe(projectDefault)
        })

        it.each([
            ['true', true],
            ['false', false],
        ])('reads filter_test_accounts=%s from the URL on a shell path', (raw, expected) => {
            filterTestAccountsDefaultsLogic.mount()
            filterTestAccountsDefaultsLogic.actions.setLocalDefault(!expected)

            mountAt(`${urls.aiObservabilityErrors()}?filter_test_accounts=${raw}`)

            expect(logic.values.filterTestAccounts).toBe(expected)
        })

        it('ignores filter_test_accounts on a non-shell path and leaves its url alone', () => {
            mountAt(TRACES)
            const outside = `${urls.webAnalytics()}?filter_test_accounts=true`
            const before = logic.values.filterTestAccounts

            router.actions.push(outside)

            expect(logic.values.filterTestAccounts).toBe(before)
            expect(
                JSON.parse(
                    localStorage.getItem(buildAiObservabilityStorageConfig('shell.filterTestAccounts').storageKey) ??
                        'null'
                )
            ).toBeNull()
            expect(router.values.searchParams).toEqual({ filter_test_accounts: true })
        })

        it.each([
            ['the same project', MOCK_DEFAULT_TEAM.id, true],
            ['another project', MOCK_DEFAULT_TEAM.id + 1, false],
        ])('keeps a remembered choice to its project, reading it back in %s', (_name, nextTeamId, expected) => {
            mountAt(TRACES)
            logic.actions.setFilterTestAccounts(true)
            logic.unmount()
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: nextTeamId })
            filterTestAccountsDefaultsLogic.mount()
            filterTestAccountsDefaultsLogic.actions.setLocalDefault(false)

            mountAt(urls.aiObservabilityErrors())

            expect(logic.values.filterTestAccounts).toBe(expected)
        })

        it('writes a toggle to the url in place and keeps the other params', () => {
            mountAt(`${TRACES}?date_from=-24h`)

            logic.actions.setFilterTestAccounts(true)

            expect(router.values.searchParams).toEqual({ date_from: '-24h', filter_test_accounts: 'true' })
            expect(router.values.lastMethod).toEqual('REPLACE')
        })

        it('does not write the project default to the url', () => {
            mountAt(TRACES)

            expect(router.values.searchParams).toEqual({})
        })
    })
})
