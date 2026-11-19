import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { SessionListApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { SESSIONS_LIST_FILTERS, sessionsListLogic } from './sessionsListLogic'
import { makeSessionListPage } from './testFixtures'

const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const LIST_PATH = urls.aiObservabilitySessions()
const FIRST_PAGE = makeSessionListPage(['session-a', 'session-b'], { nextCursor: 'cursor-2' })
const SECOND_PAGE = makeSessionListPage(['session-c'])
const FIRST_PAGE_PARAMS = { date_from: '-7d', filter_test_accounts: 'false', limit: '50' }
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-4'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

type Answer = [number, SessionListApi | { detail: string }]

describe('sessionsListLogic', () => {
    let requests: Record<string, string>[] = []
    let answer: (params: URLSearchParams) => Answer
    let logic: ReturnType<typeof sessionsListLogic.build>

    const ids = (): string[] => logic.values.items.map((item) => item.id)

    async function mountAt(url: string): Promise<void> {
        router.actions.push(url)
        logic = sessionsListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        answer = (params) => [200, params.get('cursor') === 'cursor-2' ? SECOND_PAGE : FIRST_PAGE]
        useMocks({
            get: {
                [SESSIONS_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(Object.fromEntries(params))
                    return answer(params)
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('loads the first page on mount', async () => {
        await mountAt(LIST_PATH)

        expect(requests).toEqual([FIRST_PAGE_PARAMS])
        expect(ids()).toEqual(['session-a', 'session-b'])
        expect(logic.values).toMatchObject({ state: 'ready', canShowNext: true, canShowPrevious: false })
    })

    it('reads the filters in the url without a trace view or search the sessions endpoint does not take', async () => {
        await mountAt(
            `${LIST_PATH}?filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}&view=errors&trace_search=refund`
        )

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, properties: JSON.stringify([MODEL_FILTER]) }])
    })

    it('next page uses nextCursor and keeps the pages it has', async () => {
        await mountAt(LIST_PATH)

        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()
        expect(requests[1]).toEqual({ ...FIRST_PAGE_PARAMS, cursor: 'cursor-2' })
        expect(ids()).toEqual(['session-c'])
        expect(logic.values).toMatchObject({ canShowNext: false, canShowPrevious: true })

        logic.actions.showPreviousPage()
        expect(ids()).toEqual(['session-a', 'session-b'])
        expect(requests).toHaveLength(2)
    })

    it.each([
        [
            'a filter',
            () => listFiltersLogic(SESSIONS_LIST_FILTERS).actions.setPropertyFilters([MODEL_FILTER]),
            { ...FIRST_PAGE_PARAMS, properties: JSON.stringify([MODEL_FILTER]) },
        ],
        [
            'the date range',
            () => shellScopeLogic.actions.setDateRange('-24h', null),
            { ...FIRST_PAGE_PARAMS, date_from: '-24h' },
        ],
    ])('filters change resets to first page when %s changes', async (_name, change, params) => {
        await mountAt(LIST_PATH)
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        change()
        expect(logic.values).toMatchObject({ items: [], state: 'loading', pageIndex: 0 })

        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual(params)
        expect(ids()).toEqual(['session-a', 'session-b'])
    })

    it('openSession writes the session param and drops drawer params', async () => {
        await mountAt(`${LIST_PATH}?trace=trace-9&ts=2026-09-01T10:00:00Z&step=gen-1&date_from=-7d`)
        expect(logic.values.openSessionId).toBeNull()

        logic.actions.openSession('session-b')

        expect(router.values.searchParams).toEqual({ session: 'session-b', date_from: '-7d' })
        expect(logic.values.openSessionId).toEqual('session-b')

        logic.actions.openSession(null)

        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
        expect(logic.values.openSessionId).toBeNull()
    })

    it('reads the open session from the url only on the sessions path', async () => {
        await mountAt(`${urls.aiObservabilityTraces()}?session=session-b`)

        expect(logic.values.openSessionId).toBeNull()
    })

    it('shows the error when the first page fails with nothing on screen', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        answer = () => [500, { detail: 'boom' }]

        await mountAt(LIST_PATH)

        expect(logic.values).toMatchObject({ items: [], state: 'error' })
        expect(toastError).not.toHaveBeenCalled()
    })

    it.each([
        ['nothing narrows the selection', '', 'empty'],
        ['a property filter is on', `filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}`, 'empty-filtered'],
        ['test accounts are filtered out', 'filter_test_accounts=true', 'empty-filtered'],
    ])('shows an empty first page as %s', async (_name, query, state) => {
        answer = () => [200, makeSessionListPage([])]

        await mountAt(`${LIST_PATH}?${query}`)

        expect(logic.values.state).toEqual(state)
    })
})
