import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { ErrorFirstSeenListApi, ErrorListApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { errorFirstSeenLogic } from './errorFirstSeenLogic'
import { ERRORS_LIST_FILTERS, errorsListLogic } from './errorsListLogic'
import {
    CHECKED_FROM,
    ERRORS_URL,
    ERROR_FIRST_SEEN_URL,
    makeErrorFirstSeen,
    makeErrorFirstSeenList,
    makeErrorListPage,
} from './testFixtures'

const LIST_PATH = urls.aiObservabilityErrors()
const SELECTION_PARAMS = { date_from: '-7d', filter_test_accounts: 'false' }
type FirstSeenAnswer = [number, ErrorFirstSeenListApi | { detail: string }]

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

function pageAt(params: URLSearchParams): ErrorListApi {
    const offset = Number(params.get('offset'))
    return makeErrorListPage([`error-${offset}`, `error-${offset + 1}`], { count: 120 })
}

function keysOf(body: unknown): string[] {
    if (typeof body !== 'object' || body === null || !('keys' in body) || !Array.isArray(body.keys)) {
        throw new Error('The first seen read sent no keys')
    }
    return body.keys.filter((key): key is string => typeof key === 'string')
}

describe('errorFirstSeenLogic', () => {
    let reads: { params: Record<string, string>; keys: string[] }[] = []
    let answer: (keys: string[]) => FirstSeenAnswer | Promise<FirstSeenAnswer>
    let logic: ReturnType<typeof errorFirstSeenLogic.build>

    const statuses = (keys: string[]): string[] => keys.map((key) => logic.values.firstSeen.get(key)?.status ?? 'none')

    async function settle(): Promise<void> {
        await expectLogic(errorsListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    async function mount(): Promise<void> {
        router.actions.push(LIST_PATH)
        logic = errorFirstSeenLogic()
        logic.mount()
        await settle()
    }

    beforeEach(() => {
        localStorage.clear()
        reads = []
        answer = (keys) => [200, makeErrorFirstSeenList(keys.map((key) => makeErrorFirstSeen(key)))]
        useMocks({
            get: {
                [ERRORS_URL]: ({ request }) => [200, pageAt(new URL(request.url).searchParams)],
            },
            post: {
                [ERROR_FIRST_SEEN_URL]: async ({ request }) => {
                    const keys = keysOf(await request.json())
                    reads.push({ params: Object.fromEntries(new URL(request.url).searchParams), keys })
                    return answer(keys)
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reads first seen for the shown keys after the rows, with the selection of the page', async () => {
        router.actions.push(LIST_PATH, { error_search: 'timeout', view: 'new', order: 'users' })
        logic = errorFirstSeenLogic()
        logic.mount()
        expect(statuses(['error-0', 'error-1'])).toEqual(['none', 'none'])

        await settle()

        expect(reads).toEqual([{ params: SELECTION_PARAMS, keys: ['error-0', 'error-1'] }])
        expect(logic.values.firstSeen.get('error-0')).toEqual({
            status: 'ready',
            value: { firstSeen: '2026-09-02T08:30:00Z', checkedFrom: CHECKED_FROM, isNew: false },
        })
    })

    it('gives every key the checked date and the new verdict the server sends, with no first seen when it sends none', async () => {
        answer = () => [
            200,
            {
                items: [
                    makeErrorFirstSeen('error-0', { isNew: true }),
                    makeErrorFirstSeen('error-1', { firstSeen: null }),
                ],
                checkedFrom: '2026-07-30',
            },
        ]

        await mount()

        expect([logic.values.firstSeen.get('error-0'), logic.values.firstSeen.get('error-1')]).toEqual([
            { status: 'ready', value: { firstSeen: '2026-09-02T08:30:00Z', checkedFrom: '2026-07-30', isNew: true } },
            { status: 'ready', value: { firstSeen: null, checkedFrom: '2026-07-30', isNew: false } },
        ])
    })

    it('marks the keys of a failed read as failed, not as missing, and tracks it', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        answer = () => [500, { detail: 'boom' }]

        await mount()

        expect(statuses(['error-0', 'error-1'])).toEqual(['error', 'error'])
        expect(capture).toHaveBeenCalledWith('llma diagnostics read failed', { kind: 'error', read: 'first_seen' })
    })

    it('reads only the keys of another page, and every shown key again on a reload', async () => {
        await mount()

        errorsListLogic.actions.setPageIndex(1)
        await settle()
        errorsListLogic.actions.reload()
        await settle()

        expect(reads.map((read) => read.keys)).toEqual([
            ['error-0', 'error-1'],
            ['error-50', 'error-51'],
            ['error-50', 'error-51'],
        ])
    })

    it('keeps the answer of the latest reload when an older one lands after it', async () => {
        await mount()
        const older = deferred()
        let reload = 0
        answer = async (keys) => {
            reload += 1
            const firstSeen = reload === 1 ? '2026-09-01T00:00:00Z' : '2026-09-03T00:00:00Z'
            if (reload === 1) {
                await older.promise
            }
            return [200, makeErrorFirstSeenList(keys.map((key) => makeErrorFirstSeen(key, { firstSeen })))]
        }

        errorsListLogic.actions.reload()
        await waitFor(() => expect(reads).toHaveLength(2))
        errorsListLogic.actions.reload()
        await waitFor(() => expect(reads).toHaveLength(3))
        await waitFor(() =>
            expect(logic.values.firstSeen.get('error-0')).toMatchObject({
                value: { firstSeen: '2026-09-03T00:00:00Z' },
            })
        )
        older.resolve()
        await settle()

        expect(logic.values.firstSeen.get('error-0')).toMatchObject({
            status: 'ready',
            value: { firstSeen: '2026-09-03T00:00:00Z' },
        })
    })

    it('keeps what it read when a change cannot move when an error was first seen', async () => {
        await mount()

        listFiltersLogic(ERRORS_LIST_FILTERS).actions.setSearch('timeout')
        await settle()
        listFiltersLogic(ERRORS_LIST_FILTERS).actions.setPropertyFilters([
            {
                key: '$ai_model',
                value: ['example-model'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ])
        await settle()

        expect(reads).toHaveLength(1)
        expect(statuses(['error-0', 'error-1'])).toEqual(['ready', 'ready'])
    })

    it('forgets what it read when the range or the test account switch changes, and drops an answer for the ones before', async () => {
        await mount()
        const held = deferred()
        answer = async (keys) => {
            if (keys.includes('error-50')) {
                await held.promise
            }
            return [200, makeErrorFirstSeenList(keys.map((key) => makeErrorFirstSeen(key)))]
        }
        errorsListLogic.actions.setPageIndex(1)
        await waitFor(() => expect(reads).toHaveLength(2))

        shellScopeLogic.actions.setFilterTestAccounts(true)
        expect(statuses(['error-0', 'error-50'])).toEqual(['none', 'none'])
        await waitFor(() => expect(statuses(['error-0'])).toEqual(['ready']))
        held.resolve()
        await settle()

        expect(reads.at(-1)).toEqual({
            params: { ...SELECTION_PARAMS, filter_test_accounts: 'true' },
            keys: ['error-0', 'error-1'],
        })
        expect(statuses(['error-0', 'error-50'])).toEqual(['ready', 'none'])
    })
})
