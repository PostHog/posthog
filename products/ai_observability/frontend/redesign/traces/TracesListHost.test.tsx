import { RenderResult, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceListApi } from '../../generated/api.schemas'
import { makeTraceListItem, makeTraceListPage } from './testFixtures'
import { TracesListHost } from './TracesListHost'
import { tracesListLogic } from './tracesListLogic'

const TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
const LIST_PATH = urls.aiObservabilityTraces()
const SEARCH_FLAG = FEATURE_FLAGS.LLM_OBSERVABILITY_TRACE_SEARCH
const FIRST_PAGE_PARAMS = { date_from: '-7d', filter_test_accounts: 'false', limit: '50' }
const PAGE: TraceListApi = {
    items: [
        makeTraceListItem({ id: 'trace-a', name: 'answer-billing-question' }),
        makeTraceListItem({ id: 'trace-b', name: 'summarize-ticket' }),
    ],
    counts: { total: 2, errors: 1, feedback: 3 },
    nextCursor: null,
}

type Answer = [number, TraceListApi | { detail: string }]

function attr(view: RenderResult, name: string): HTMLElement {
    const element = view.container.querySelector<HTMLElement>(`[data-attr="${name}"]`)
    if (!element) {
        throw new Error(`expected ${name} to render`)
    }
    return element
}

describe('TracesListHost', () => {
    let requests: Record<string, string>[] = []
    let answer: Answer

    beforeEach(() => {
        requests = []
        answer = [200, PAGE]
        useMocks({
            get: {
                [TRACES_URL]: ({ request }) => {
                    requests.push(Object.fromEntries(new URL(request.url).searchParams))
                    return answer
                },
            },
        })
        initKeaTests()
        localStorage.clear()
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    function renderHost({ flags = [], url = LIST_PATH }: { flags?: string[]; url?: string } = {}): RenderResult {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        router.actions.push(url)
        return render(<TracesListHost />)
    }

    async function settled(): Promise<void> {
        await expectLogic(tracesListLogic()).toFinishAllListeners()
    }

    it('shows the rows of the first page and the counts on the chips', async () => {
        const view = renderHost()
        await view.findByText('summarize-ticket')

        expect(view.getByText('answer-billing-question')).toBeTruthy()
        expect(attr(view, 'ai-observability-traces-list-quick-filter-errors').textContent).toBe('Errors1')
        expect(attr(view, 'ai-observability-traces-list-quick-filter-feedback').textContent).toBe('User feedback3')
        expect(requests).toEqual([FIRST_PAGE_PARAMS])
    })

    it('opens a clicked row in the drawer without reloading the list or moving its full page link', async () => {
        const view = renderHost()
        const link = (await view.findByText('summarize-ticket')).closest('a')
        const row = link?.closest('tr')
        if (!link || !row) {
            throw new Error('expected the trace to render as a link in a row')
        }
        const href = link.getAttribute('href') ?? ''

        fireEvent.click(row.querySelectorAll('td')[0])
        await settled()

        expect(router.values.location.pathname).toContain(LIST_PATH)
        expect(router.values.searchParams).toMatchObject({ trace: 'trace-b', ts: '2026-09-01T10:15:00Z' })
        expect(requests).toHaveLength(1)
        expect(combineUrl(href).pathname).toContain(urls.aiObservabilityTrace('trace-b'))
        expect(combineUrl(href).searchParams).toEqual({
            timestamp: '2026-09-01T10:15:00Z',
            back_to: 'traces',
            back_url: LIST_PATH,
        })
        expect(link.getAttribute('href')).toBe(href)
    })

    it('reads the errors view from the errors chip', async () => {
        const view = renderHost()
        await view.findByText('summarize-ticket')

        fireEvent.click(attr(view, 'ai-observability-traces-list-quick-filter-errors'))
        await waitFor(() => expect(requests).toHaveLength(2))

        expect(router.values.searchParams.view).toBe('errors')
        expect(requests[1]).toEqual({ ...FIRST_PAGE_PARAMS, view: 'errors' })
    })

    it('shows what is being typed in the search box while the list still reads the applied search', async () => {
        const view = renderHost({ flags: [SEARCH_FLAG] })
        await view.findByText('summarize-ticket')
        const box = view.getByPlaceholderText('Search inputs and outputs')

        fireEvent.change(box, { target: { value: 'refund' } })

        expect(box.getAttribute('value')).toBe('refund')
        expect(requests).toEqual([FIRST_PAGE_PARAMS])
    })

    it('hides the search box with the search flag off', async () => {
        const view = renderHost({ url: `${LIST_PATH}?trace_search=refund` })
        await view.findByText('summarize-ticket')

        expect(view.queryByPlaceholderText('Search inputs and outputs')).toBeNull()
        expect(requests).toEqual([FIRST_PAGE_PARAMS])
    })

    it.each([
        ['the browser default when the person has not chosen', true, '', true],
        ['no filtering when neither is on', false, '', false],
        ["the person's choice over the browser default", true, '?filter_test_accounts=false', false],
        ["the person's choice when the browser default is off", false, '?filter_test_accounts=true', true],
    ])('shows and sends %s', async (_name, browserDefault, query, filtered) => {
        filterTestAccountsDefaultsLogic.mount()
        filterTestAccountsDefaultsLogic.actions.setLocalDefault(browserDefault)

        const view = renderHost({ url: `${LIST_PATH}${query}` })
        await view.findByText('summarize-ticket')

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, filter_test_accounts: String(filtered) }])
        expect(view.container.querySelector('#test-account-filter')?.getAttribute('aria-checked')).toBe(
            String(filtered)
        )
    })

    it('turns test account filtering off with the other filters when clearing them, even when the default is on', async () => {
        filterTestAccountsDefaultsLogic.mount()
        filterTestAccountsDefaultsLogic.actions.setLocalDefault(true)
        answer = [200, makeTraceListPage([])]
        const view = renderHost({ url: `${LIST_PATH}?view=errors` })

        fireEvent.click(await view.findByText('Clear filters'))
        await waitFor(() => expect(requests).toHaveLength(2))

        expect(requests[1]).toEqual({ ...FIRST_PAGE_PARAMS, filter_test_accounts: 'false' })
        expect(tracesListLogic().values.filterTestAccounts).toBe(false)
    })

    it.each<[string, Answer, string, string, string]>([
        [
            'empty',
            [200, makeTraceListPage([])],
            '',
            'No traces in this date range',
            'Pick a wider date range to see older traces.',
        ],
        ['filtered empty', [200, makeTraceListPage([])], '?view=errors', 'No traces match', 'Clear filters'],
        ['error', [500, { detail: 'Something broke.' }], '', 'Could not load traces', 'Retry'],
    ])('shows the %s state', async (_name, reply, query, title, detail) => {
        silenceKeaLoadersErrors()
        answer = reply

        const view = renderHost({ url: `${LIST_PATH}${query}` })

        expect(await view.findByText(title)).toBeTruthy()
        expect(view.getByText(detail)).toBeTruthy()
    })
})
