import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { type ToolListApi, ToolOrderApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { TOOLS_URL, makeToolListPage } from './testFixtures'
import { TOOLS_LIST_FILTERS, toolsListLogic } from './toolsListLogic'

const LIST_PATH = urls.aiObservabilityTools()
const COUNTS = { total: 80, failing: 3, maxCalls: 1240 }
const PAGE_PARAMS = { date_from: '-7d', filter_test_accounts: 'false', limit: '50', offset: '0' }

type Answer = [number, ToolListApi | Record<string, string>]

function pageAt(params: URLSearchParams): ToolListApi {
    const offset = Number(params.get('offset'))
    const order = Object.values(ToolOrderApi).find((value) => value === params.get('order')) ?? 'calls'
    return makeToolListPage([`tool-${offset}`, `tool-${offset + 1}`], { count: COUNTS.total, counts: COUNTS, order })
}

describe('toolsListLogic', () => {
    let requests: Record<string, string>[] = []
    let answer: (params: URLSearchParams) => Answer | Promise<Answer>
    let logic: ReturnType<typeof toolsListLogic.build>

    async function mountAt(url: string): Promise<void> {
        router.actions.push(url)
        logic = toolsListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        answer = (params) => [200, pageAt(params)]
        useMocks({
            get: {
                [TOOLS_URL]: ({ request }) => {
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

    it('loads the first page of the last seven days with no order, sorted as the api says, with its counts', async () => {
        await mountAt(LIST_PATH)

        expect(requests).toEqual([PAGE_PARAMS])
        expect(logic.values.items.map((item) => item.key)).toEqual(['tool-0', 'tool-1'])
        expect(logic.values).toMatchObject({
            counts: COUNTS,
            order: null,
            sortedBy: 'calls',
            state: 'ready',
            canShowNext: true,
        })
    })

    it('keeps the order the api last applied while the next page loads', async () => {
        await mountAt(LIST_PATH)
        let release = (): void => {}
        const held = new Promise<void>((done) => {
            release = done
        })
        answer = async (params) => {
            await held
            return [200, pageAt(params)]
        }

        listFiltersLogic(TOOLS_LIST_FILTERS).actions.setSearch('lookup')

        expect(logic.values).toMatchObject({ state: 'loading', sortedBy: 'calls' })
        release()
        await expectLogic(logic).toFinishAllListeners()
    })

    it.each([
        [
            'its search, view and order',
            'tool_search=orders&view=failing&order=failure_rate',
            { search: 'orders', view: 'failing', order: 'failure_rate' },
        ],
        ["the errors list's search, which is not its own", 'error_search=timeout', {}],
        ["the errors list's view and order, which the api does not know", 'view=increasing&order=occurrences', {}],
    ])('reads once from the url at mount: %s', async (_name, query, params) => {
        await mountAt(`${LIST_PATH}?${query}`)

        expect(requests).toEqual([{ ...PAGE_PARAMS, ...params }])
    })

    it('reads page one again in the order chosen and writes the order to the url', async () => {
        await mountAt(`${LIST_PATH}?tool_search=orders`)
        logic.actions.setPageIndex(1)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setOrder('traces')
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.slice(2)).toEqual([{ ...PAGE_PARAMS, search: 'orders', order: 'traces' }])
        expect(router.values.searchParams).toMatchObject({ tool_search: 'orders', order: 'traces' })
    })

    it('sends the failing view of the quick filter', async () => {
        await mountAt(LIST_PATH)

        listFiltersLogic(TOOLS_LIST_FILTERS).actions.toggleQuickFilter('failing')
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({ ...PAGE_PARAMS, view: 'failing' })
    })

    it('shows the setup state when no tool call was ever captured', async () => {
        answer = () => [200, makeToolListPage([], { nothingCaptured: true })]

        await mountAt(`${LIST_PATH}?tool_search=orders`)

        expect(logic.values).toMatchObject({ state: 'empty', nothingCaptured: true })
    })

    it('shows a failed first page and reports it as a failed tools read', async () => {
        silenceKeaLoadersErrors()
        const capture = jest.spyOn(posthog, 'capture')
        answer = () => [500, { detail: 'boom' }]

        await mountAt(LIST_PATH)

        expect(logic.values.state).toEqual('error')
        expect(capture.mock.calls.filter(([event]) => event.startsWith('llma diagnostics'))).toEqual([
            ['llma diagnostics read failed', { kind: 'tool', read: 'list' }],
        ])
    })
})
