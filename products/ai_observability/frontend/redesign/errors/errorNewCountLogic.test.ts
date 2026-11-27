import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ErrorNewCountApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { errorNewCountLogic } from './errorNewCountLogic'
import { ERRORS_LIST_FILTERS, errorsListLogic } from './errorsListLogic'
import { ERRORS_URL, ERROR_NEW_COUNT_URL, makeErrorListPage } from './testFixtures'

const LIST_PATH = urls.aiObservabilityErrors()
const SELECTION_PARAMS = { date_from: '-7d', filter_test_accounts: 'false' }
const RANGE_TOO_LONG = { code: 'range_too_long', detail: 'Pick a range of 90 days or less.' }

type Answer = [number, ErrorNewCountApi | Record<string, string>]

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

describe('errorNewCountLogic', () => {
    let reads: Record<string, string>[] = []
    let answer: () => Answer | Promise<Answer>
    let logic: ReturnType<typeof errorNewCountLogic.build>

    async function settle(): Promise<void> {
        await expectLogic(errorsListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    async function mountAt(search: Record<string, string> = {}): Promise<void> {
        router.actions.push(LIST_PATH, search)
        logic = errorNewCountLogic()
        logic.mount()
        await settle()
    }

    beforeEach(() => {
        localStorage.clear()
        reads = []
        answer = () => [200, { count: 3 }]
        useMocks({
            get: {
                [ERRORS_URL]: () => [200, makeErrorListPage(['error-0', 'error-1'], { count: 120 })],
                [ERROR_NEW_COUNT_URL]: ({ request }) => {
                    reads.push(Object.fromEntries(new URL(request.url).searchParams))
                    return answer()
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

    it('reads the count of the selection without its view or order, showing it as loading until it lands', async () => {
        const held = deferred()
        answer = async () => {
            await held.promise
            return [200, { count: 3 }]
        }
        router.actions.push(LIST_PATH, { error_search: 'timeout', view: 'increasing', order: 'users' })
        logic = errorNewCountLogic()
        logic.mount()

        await waitFor(() => expect(errorsListLogic.values.state).toEqual('ready'))
        expect(logic.values.newCountLoad).toEqual({ status: 'loading' })

        held.resolve()
        await settle()

        expect(reads).toEqual([{ ...SELECTION_PARAMS, search: 'timeout' }])
        expect(logic.values.newCountLoad).toEqual({ status: 'ready', value: 3 })
    })

    it.each<[string, Answer, unknown, unknown[]]>([
        [
            'a failed read',
            [500, { detail: 'boom' }],
            { status: 'error' },
            [['llma diagnostics read failed', { kind: 'error', read: 'new_count' }]],
        ],
        ['a range that is too long', [422, RANGE_TOO_LONG], null, []],
    ])('settles %s without a toast and tracks only a failed read', async (_name, failed, load, events) => {
        silenceKeaLoadersErrors()
        const capture = jest.spyOn(posthog, 'capture')
        const toastError = jest.spyOn(lemonToast, 'error')
        answer = () => failed

        await mountAt()

        expect(logic.values.newCountLoad).toEqual(load)
        expect(capture.mock.calls.filter(([event]) => event.startsWith('llma diagnostics'))).toEqual(events)
        expect(toastError).not.toHaveBeenCalled()
    })

    it.each([
        ['the view', () => listFiltersLogic(ERRORS_LIST_FILTERS).actions.toggleQuickFilter('new')],
        ['the order', () => errorsListLogic.actions.setOrder('change')],
        ['the page', () => errorsListLogic.actions.setPageIndex(1)],
    ])('does not read again when %s changes', async (_name, change) => {
        await mountAt()

        change()
        await settle()

        expect(reads).toHaveLength(1)
        expect(logic.values.newCountLoad).toEqual({ status: 'ready', value: 3 })
    })

    it.each([
        ['the search', () => listFiltersLogic(ERRORS_LIST_FILTERS).actions.setSearch('timeout'), { search: 'timeout' }],
        ['the date range', () => shellScopeLogic.actions.setDateRange('-24h', null), { date_from: '-24h' }],
        ['a reload', () => errorsListLogic.actions.reload(), {}],
    ])('reads again on %s', async (_name, change, params) => {
        await mountAt()

        change()
        await settle()

        expect(reads).toEqual([SELECTION_PARAMS, { ...SELECTION_PARAMS, ...params }])
    })
})
