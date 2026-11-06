import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceSearchResultsApi } from '../../generated/api.schemas'
import { makeTraceResource } from './adapter/testFixtures'
import { SEARCH_DEBOUNCE_MS, traceSearchLogic } from './traceSearchLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const SEARCH_URL = '/api/projects/:team_id/ai_observability/traces/:id/search/'
const CREATED_AT = '2026-09-01T10:15:00Z'

function resultsFor(query: string): TraceSearchResultsApi {
    return { total: query.length, matches: [{ nodeId: 'gen-1', count: query.length }] }
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

describe('traceSearchLogic', () => {
    let logic: ReturnType<typeof traceSearchLogic.build>
    let searches: { q: string | null; hint: string | null }[]
    let searchStatus: number
    let searchStatuses: Record<string, number>
    let searchGates: Record<string, Promise<void>>
    let traceGate: Promise<void>

    beforeEach(() => {
        searches = []
        searchStatus = 200
        searchStatuses = {}
        searchGates = {}
        traceGate = Promise.resolve()
        useMocks({
            get: {
                [TRACE_URL]: async () => {
                    await traceGate
                    return [200, makeTraceResource({ createdAt: CREATED_AT })]
                },
                [EVALUATIONS_URL]: () => [200, { results: [] }],
                [SEARCH_URL]: async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const q = params.get('q')
                    searches.push({ q, hint: params.get('timestamp_hint') })
                    await (searchGates[q ?? ''] ?? Promise.resolve())
                    const status = searchStatuses[q ?? ''] ?? searchStatus
                    return status === 200 ? [200, resultsFor(q ?? '')] : [status, { detail: 'nope' }]
                },
            },
        })
        initKeaTests()
        logic = traceSearchLogic({ traceId: 'trace-1', timestampHint: null })
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    async function mountWithTrace(): Promise<void> {
        logic.mount()
        await expectLogic(traceViewLogic({ traceId: 'trace-1', timestampHint: null })).toFinishAllListeners()
    }

    function typeAndWait(...queries: string[]): void {
        jest.useFakeTimers()
        for (const query of queries) {
            logic.actions.setQuery(query)
        }
        jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
    }

    it('sends one request with the trace timestamp once the typing settles', async () => {
        await mountWithTrace()

        typeAndWait('in', 'inv', 'invoice')
        await expectLogic(logic).toFinishAllListeners()

        expect(searches).toEqual([{ q: 'invoice', hint: CREATED_AT }])
        expect(logic.values).toMatchObject({ searchResults: resultsFor('invoice'), searchStatus: 'ready' })
    })

    it.each([
        ['answers', 200],
        ['fails', 500],
    ])('sends only the latest query once the request in flight %s', async (_name, firstStatus) => {
        silenceKeaLoadersErrors()
        await mountWithTrace()
        const firstAnswer = deferred()
        searchGates.first = firstAnswer.promise
        searchStatuses.first = firstStatus

        typeAndWait('first')
        await waitFor(() => expect(searches).toHaveLength(1))
        typeAndWait('second')
        typeAndWait('third')
        expect(searches).toHaveLength(1)
        firstAnswer.resolve()
        await waitFor(() => expect(logic.values.searchResults).toEqual(resultsFor('third')))

        expect(searches.map(({ q }) => q)).toEqual(['first', 'third'])
        expect(logic.values).toMatchObject({ searchFailure: null, searchStatus: 'ready' })
    })

    it('clears the results without a request when the query is blank', async () => {
        await mountWithTrace()
        typeAndWait('invoice')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setQuery('   ')
        await expectLogic(logic).toFinishAllListeners()

        expect(searches).toHaveLength(1)
        expect(logic.values).toMatchObject({ searchResults: null, searchStatus: 'idle' })
    })

    it.each([
        ['a timeout', 504, 'too_slow'],
        ['any other failure', 500, 'failed'],
    ])('names %s without a toast', async (_name, status, failure) => {
        silenceKeaLoadersErrors()
        const toast = jest.spyOn(lemonToast, 'error')
        searchStatus = status
        await mountWithTrace()

        typeAndWait('invoice')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ searchFailure: failure, searchStatus: 'error' })
        expect(toast).not.toHaveBeenCalled()
    })

    it('waits for the trace before searching a query from a link', async () => {
        const traceAnswer = deferred()
        traceGate = traceAnswer.promise
        logic.mount()

        await expectLogic(logic, () => logic.actions.setQuery('invoice')).toDispatchActions([
            'loadSearchResultsSuccess',
        ])
        expect(searches).toEqual([])
        expect(logic.values.searchStatus).toBe('loading')

        traceAnswer.resolve()
        await expectLogic(logic).toDispatchActions(['loadTraceSuccess', 'loadSearchResultsSuccess'])

        expect(searches).toEqual([{ q: 'invoice', hint: CREATED_AT }])
    })

    it('reports each search it shows', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        await mountWithTrace()

        typeAndWait('invoice')
        await expectLogic(logic).toFinishAllListeners()

        expect(capture).toHaveBeenCalledWith('llma trace view searched', {
            query_length: 7,
            total: 7,
            matching_steps: 1,
            load_ms: expect.any(Number),
        })
    })
})
