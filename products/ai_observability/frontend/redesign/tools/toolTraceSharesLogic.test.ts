import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ToolListApi, ToolTraceShareListApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TOOLS_URL, TOOL_TRACE_SHARES_URL, makeToolListPage, makeToolTraceShares } from './testFixtures'
import { TOOLS_LIST_FILTERS, toolsListLogic } from './toolsListLogic'
import { toolTraceSharesLogic } from './toolTraceSharesLogic'

const LIST_PATH = urls.aiObservabilityTools()
const SELECTION_PARAMS = { date_from: '-7d', filter_test_accounts: 'false' }
type SharesAnswer = [number, ToolTraceShareListApi | { detail: string }]

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

function pageAt(params: URLSearchParams): ToolListApi {
    const offset = Number(params.get('offset'))
    return makeToolListPage([`tool-${offset}`, `tool-${offset + 1}`], { count: 80 })
}

function keysOf(body: unknown): string[] {
    if (typeof body !== 'object' || body === null || !('keys' in body) || !Array.isArray(body.keys)) {
        throw new Error('The trace shares read sent no keys')
    }
    return body.keys.filter((key): key is string => typeof key === 'string')
}

describe('toolTraceSharesLogic', () => {
    let reads: { params: Record<string, string>; keys: string[] }[] = []
    let answer: (keys: string[]) => SharesAnswer | Promise<SharesAnswer>
    let logic: ReturnType<typeof toolTraceSharesLogic.build>

    const statuses = (keys: string[]): string[] =>
        keys.map((key) => logic.values.traceShares.get(key)?.status ?? 'none')

    async function settle(): Promise<void> {
        await expectLogic(toolsListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    async function mount(): Promise<void> {
        router.actions.push(LIST_PATH)
        logic = toolTraceSharesLogic()
        logic.mount()
        await settle()
    }

    beforeEach(() => {
        localStorage.clear()
        reads = []
        answer = (keys) => [200, makeToolTraceShares(keys.map((key) => [key, 0.25]))]
        useMocks({
            get: {
                [TOOLS_URL]: ({ request }) => [200, pageAt(new URL(request.url).searchParams)],
            },
            post: {
                [TOOL_TRACE_SHARES_URL]: async ({ request }) => {
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

    it('reads the shares of the shown keys after the rows, with the selection of the page but its search', async () => {
        router.actions.push(LIST_PATH, { tool_search: 'search', view: 'failing', order: 'traces' })
        logic = toolTraceSharesLogic()
        logic.mount()
        expect(statuses(['tool-0', 'tool-1'])).toEqual(['none', 'none'])

        await settle()

        expect(reads).toEqual([{ params: SELECTION_PARAMS, keys: ['tool-0', 'tool-1'] }])
        expect(logic.values.traceShares.get('tool-0')).toEqual({ status: 'ready', value: 0.25 })
    })

    it.each([
        ['a server error', 500],
        ['a read too heavy to run', 422],
        ['a range with no previous window', 400],
    ])('marks the keys of %s as failed and tracks it, leaving the list as it is', async (_name, status) => {
        const capture = jest.spyOn(posthog, 'capture')
        answer = () => [status, { detail: 'failed' }]

        await mount()

        expect(statuses(['tool-0', 'tool-1'])).toEqual(['error', 'error'])
        expect(toolsListLogic.values.state).toEqual('ready')
        expect(capture).toHaveBeenCalledWith('llma diagnostics read failed', { kind: 'tool', read: 'trace_shares' })
    })

    it('reads only the keys of another page, and every shown key again on a reload', async () => {
        await mount()

        toolsListLogic.actions.setPageIndex(1)
        await settle()
        toolsListLogic.actions.reload()
        await settle()

        expect(reads.map((read) => read.keys)).toEqual([
            ['tool-0', 'tool-1'],
            ['tool-50', 'tool-51'],
            ['tool-50', 'tool-51'],
        ])
    })

    it('marks the shares it showed as failed when a reload fails to read them again', async () => {
        await mount()
        answer = () => [500, { detail: 'failed' }]

        toolsListLogic.actions.reload()
        await settle()

        expect(statuses(['tool-0', 'tool-1'])).toEqual(['error', 'error'])
    })

    it('keeps what it read when only the search changes', async () => {
        await mount()

        listFiltersLogic(TOOLS_LIST_FILTERS).actions.setSearch('search')
        await settle()

        expect(reads).toHaveLength(1)
        expect(statuses(['tool-0', 'tool-1'])).toEqual(['ready', 'ready'])
    })

    it('forgets what it read when the selection changes, and drops an answer for the one before', async () => {
        await mount()
        const held = deferred()
        answer = async (keys) => {
            if (keys.includes('tool-50')) {
                await held.promise
            }
            return [200, makeToolTraceShares(keys.map((key) => [key, 0.25]))]
        }
        toolsListLogic.actions.setPageIndex(1)
        await waitFor(() => expect(reads).toHaveLength(2))

        shellScopeLogic.actions.setDateRange('-24h', null)
        expect(statuses(['tool-0', 'tool-50'])).toEqual(['none', 'none'])
        await waitFor(() => expect(statuses(['tool-0'])).toEqual(['ready']))
        held.resolve()
        await settle()

        expect(reads.at(-1)).toEqual({ params: { ...SELECTION_PARAMS, date_from: '-24h' }, keys: ['tool-0', 'tool-1'] })
        expect(statuses(['tool-0', 'tool-50'])).toEqual(['ready', 'none'])
    })
})
