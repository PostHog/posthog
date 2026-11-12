import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { NodeKind, type AccountsTableQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { parseProductUsageControls } from './productUsageControlValues'
import { DEFAULT_CONTROLS } from './productUsageControlValues'
import { productUsageGridLogic } from './productUsageGridLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({
    ...jest.requireActual('~/queries/nodes/DataNode/dataNodeLogic'),
    cancelQueryOnServer: jest.fn(),
}))
const query = performQuery as jest.Mock
const accounts: AccountsTableQueryResponse = {
    kind: NodeKind.AccountsTableQuery,
    limit: 200,
    offset: 0,
    results: [
        {
            id: 'a',
            name: 'Example',
            externalId: 'org',
            accountFields: {},
            relationships: {},
            customProperties: {},
            customPropertyHistory: {},
        },
    ],
    hasMore: false,
}
const sql = 'SELECT id AS row, 1 AS column FROM system.accounts WHERE id IN {account_ids}'

describe('productUsageGridLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        router.actions.push(urls.customerAnalyticsProductActivity())
        query.mockReset()
        jest.spyOn(posthog, 'capture').mockClear()
    })
    it.each([{ interval: ['week'] }, { interval: { toString: null } }, { interval: null }, { interval: 12 }])(
        'defaults invalid interval $interval without coercion',
        ({ interval }) => {
            expect(parseProductUsageControls({ interval }, DEFAULT_CONTROLS).interval).toBe('week')
        }
    )
    it('keeps assignment status and selected users consistent', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.setControls({ assignmentStatus: 'unassigned' })
        logic.actions.setControls({ assignedTo: [5] })
        expect(logic.values.controls.assignmentStatus).toBe('assigned')
        expect(logic.values.controls.assignedTo).toEqual([5])
        logic.actions.setControls({ assignmentStatus: 'all' })
        expect(logic.values.controls.assignedTo).toEqual([])
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
    })
    it('reloads changed filters despite subsequent presentation changes', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.setSource({ kind: 'hogql', query: sql, mapping: { row: 'row', column: 'column' } })
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ columns: ['row', 'column'], results: [] })
        await expectLogic(logic, () => {
            logic.actions.setControls({ search: 'Acorn' })
            logic.actions.setControls({ selected: ['custom'], zoom: 'count' })
        })
            .toDispatchActions(['finishLoad'])
            .toFinishAllListeners()
        expect(logic.values.result?.accounts).toEqual(accounts)
        expect(logic.values.accountFilters.search).toBe('Acorn')
        expect(query.mock.calls[0][0].filters).toContainEqual({ kind: 'search', query: 'Acorn' })
        logic.unmount()
    })
    it('supports zoom and clear shortcuts without stealing editor or browser keys', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setControls({ zoom: 'products', selected: ['logs'] })
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '-' }))
        expect(logic.values.controls.zoom).toBe('count')
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '+' }))
        expect(logic.values.controls.zoom).toBe('products')
        const input = document.createElement('input')
        document.body.append(input)
        input.dispatchEvent(new KeyboardEvent('keydown', { key: '-', bubbles: true }))
        expect(logic.values.controls.zoom).toBe('products')
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '-', ctrlKey: true }))
        expect(logic.values.controls.zoom).toBe('products')
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
        expect(logic.values.controls.selected).toEqual([])
        input.remove()
        logic.unmount()
    })
    it('bounds keyboard zoom to the displayed preview source, including unsaved queries', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts,
            matrix: BOOK_ACTIVITY_MATRIX_MOCK,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        logic.actions.setControls({ zoom: 'products' })
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '+' }))
        expect(logic.values.controls.zoom).toBe('users')
        logic.actions.setSource({ kind: 'product_usage' })
        logic.actions.finishLoad({
            accounts,
            matrix: null,
            hogql: { columns: [], results: [] },
            source: { kind: 'hogql', query: sql, mapping: { row: 'row', column: 'column', value: 'value' } },
        })
        logic.actions.setControls({ zoom: 'products' })
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '+' }))
        expect(logic.values.controls.zoom).toBe('products')
        logic.unmount()
    })
    it('keeps series selections with their source across previews, empty refreshes and cancel', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_PRODUCT_USAGE]: true })
        logic.actions.setSource({ kind: 'product_usage' })
        logic.actions.finishLoad({
            accounts,
            matrix: BOOK_ACTIVITY_MATRIX_MOCK,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        logic.actions.setControls({ selected: ['logs'] })
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({
            columns: ['row', 'column', 'series', 'value'],
            results: [['a', 'week', 'custom', 5]],
        })
        await expectLogic(logic, () => logic.actions.runQuery()).toFinishAllListeners()
        expect(logic.values.controls.selected).toEqual([])
        expect(router.values.searchParams.activity.selected).toEqual([])
        expect(logic.values.result?.hogql?.results).toEqual([['a', 'week', 'custom', 5]])

        logic.actions.setControls({ selected: ['custom'] })
        query
            .mockResolvedValueOnce(accounts)
            .mockResolvedValueOnce({ columns: ['row', 'column', 'series', 'value'], results: [] })
        await expectLogic(logic, () => logic.actions.runQuery()).toFinishAllListeners()
        expect(logic.values.controls.selected).toEqual(['custom'])

        logic.actions.setMappingDraft({ row: 'row', column: 'column', value: 'value' })
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({
            columns: ['row', 'column', 'series', 'value'],
            results: [['a', 'week', 'custom', 5]],
        })
        await expectLogic(logic, () => logic.actions.runQuery()).toFinishAllListeners()
        expect(logic.values.controls.selected).toEqual([])
        expect(router.values.searchParams.activity.selected).toEqual([])

        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ results: BOOK_ACTIVITY_MATRIX_MOCK })
        await expectLogic(logic, () => logic.actions.cancelEditor()).toFinishAllListeners()
        expect(logic.values.controls.selected).toEqual(['logs'])
        expect(router.values.searchParams.activity.selected).toEqual(['logs'])
        expect(logic.values.result?.source.kind).toBe('product_usage')
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        const customResult = { columns: ['row', 'column', 'series', 'value'], results: [['a', 'week', 'custom', 5]] }
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce(customResult)
        await expectLogic(logic, () => logic.actions.runQuery()).toFinishAllListeners()
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce(customResult)
        await expectLogic(logic, () => logic.actions.saveSource()).toFinishAllListeners()
        const selectedBeforeReload = logic.values.controls.selected
        expect(router.values.searchParams.activity.selected).toEqual(selectedBeforeReload)
        logic.unmount()
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce(customResult)
        const reloaded = productUsageGridLogic()
        reloaded.mount()
        await expectLogic(reloaded).toFinishAllListeners()
        expect(reloaded.values.source?.kind).toBe('hogql')
        expect(reloaded.values.controls.selected).toEqual(selectedBeforeReload)
        expect(reloaded.values.controls.selected).not.toContain('logs')
        reloaded.unmount()
    })
    it('keeps account navigation when a book query finishes before the old logic unmounts', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        let resolve!: (value: unknown) => void
        query
            .mockImplementationOnce(
                () =>
                    new Promise((done) => {
                        resolve = done
                    })
            )
            .mockResolvedValueOnce({ columns: ['row', 'column'], results: [['a', 1]] })
        logic.actions.runQuery()
        router.actions.push(urls.customerAnalyticsAccount('a'))
        const accountPath = router.values.location.pathname
        resolve(accounts)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.result?.accounts).toEqual(accounts)
        expect(router.values.location.pathname).toBe(accountPath)
        expect(router.values.searchParams.activity).toBeUndefined()
        logic.unmount()
    })
    it('keeps a new book blank until Run, and saves only a successful executed query', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(query).not.toHaveBeenCalled()
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        expect(query).not.toHaveBeenCalled()
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ columns: ['row', 'column'], results: [['a', 1]] })
        await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['finishLoad'])
        expect(logic.values.querySaveError).toBeNull()
        expect(posthog.capture).toHaveBeenCalledWith('customer analytics product activity query run', {
            source_kind: 'hogql',
        })
        expect(posthog.capture).toHaveBeenCalledWith('customer analytics product activity query completed', {
            source_kind: 'hogql',
            account_count: 1,
            truncated: false,
        })
        logic.actions.setQueryDraft(sql + ' LIMIT 10')
        expect(logic.values.querySaveError).toBe('Run this query before saving.')
        logic.actions.cancelEditor()
        expect(logic.values.result).toBeNull()
        expect(localStorage.getItem(logic.values.storageKey)).toBeNull()
        logic.unmount()
    })
    it('saves the executed source in private browser storage and reports success', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ columns: ['row', 'column'], results: [['a', 1]] })
        await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['finishLoad'])
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ columns: ['row', 'column'], results: [['a', 1]] })
        await expectLogic(logic, () => logic.actions.saveSource()).toDispatchActions(['setSource', 'finishLoad'])
        expect(query.mock.calls.slice(0, 2).map((call) => call[2])).toEqual(['force_blocking', 'force_blocking'])
        expect(query.mock.calls.slice(2, 4).map((call) => call[2])).toEqual(['blocking', 'blocking'])
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ columns: ['row', 'column'], results: [['a', 1]] })
        await expectLogic(logic, () => logic.actions.refresh()).toDispatchActions(['finishLoad'])
        expect(query.mock.calls.slice(4, 6).map((call) => call[2])).toEqual(['force_blocking', 'force_blocking'])
        expect(JSON.parse(localStorage.getItem(logic.values.storageKey)!)).toEqual(logic.values.source)
        expect(logic.values.editorOpen).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith('customer analytics product activity source saved', {
            source_kind: 'hogql',
        })
        logic.unmount()
    })
    it('blocks the product starter before sending a query when its flag is off', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.openEditor('product_usage')
        await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['failLoad'])
        expect(query).not.toHaveBeenCalled()
        expect(logic.values.error).toContain('Product usage is unavailable')
        logic.unmount()
    })
    it.each(['product_usage', 'usage_metrics'])('restores only a supported saved book source: %s', async (kind) => {
        const initial = productUsageGridLogic()
        initial.mount()
        const key = initial.values.storageKey
        initial.unmount()
        localStorage.setItem(key, JSON.stringify({ kind }))
        const restored = productUsageGridLogic()
        restored.mount()
        await expectLogic(restored).toFinishAllListeners()
        expect(restored.values.source).toEqual(kind === 'product_usage' ? { kind: 'product_usage' } : null)
        expect(query).not.toHaveBeenCalled()
        restored.unmount()
    })
    it('keeps the source and draft when browser storage rejects a save', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        query.mockResolvedValueOnce(accounts).mockResolvedValueOnce({ columns: ['row', 'column'], results: [['a', 1]] })
        await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['finishLoad'])
        const save = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('quota')
        })
        logic.actions.saveSource()
        expect(logic.values.source).toBeNull()
        expect(logic.values.editorOpen).toBe(true)
        expect(logic.values.queryDraft).toBe(sql)
        expect(logic.values.saveError).toContain('Your query is still here')
        expect(posthog.capture).toHaveBeenCalledWith('customer analytics product activity source save failed', {
            source_kind: 'hogql',
        })
        save.mockRestore()
        logic.unmount()
    })
    it('retains people previews when optional history fails and retries history independently', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts,
            matrix: BOOK_ACTIVITY_MATRIX_MOCK,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        const people = {
            rows: BOOK_ACTIVITY_MATRIX_MOCK.rows.slice(0, 5),
            columns: BOOK_ACTIVITY_MATRIX_MOCK.columns,
            people: [
                {
                    row: BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key,
                    column: BOOK_ACTIVITY_MATRIX_MOCK.columns[0].key,
                    series: 'pa',
                    personId: 'example-person',
                    label: 'person@example.com',
                    rank: 1,
                    engagedSeconds: 120,
                    actionCount: 1,
                    actions: [],
                    topPaths: [],
                },
            ],
            truncated: false,
        }
        query.mockImplementation((node) =>
            node.kind === NodeKind.BookActivityPeopleQuery
                ? Promise.resolve({ results: people })
                : Promise.reject(new Error('history unavailable'))
        )
        await expectLogic(logic, () =>
            logic.actions.setControls({ zoom: 'users', firstUse: true })
        ).toFinishAllListeners()
        expect(logic.values.details.people).toEqual(people)
        expect(logic.values.details.firsts).toBeNull()
        expect(logic.values.detailsError).toBe('Could not load first-use history. Try again.')
        expect(logic.values.detailsLoading).toBe(false)
        const firsts = { accounts: [], people: [], truncated: false }
        query.mockImplementation((node) =>
            node.kind === NodeKind.BookActivityFirstsQuery
                ? Promise.resolve({ results: firsts })
                : Promise.reject(new Error('people should remain available'))
        )
        await expectLogic(logic, () => logic.actions.retryDetails()).toFinishAllListeners()
        expect(logic.values.details).toEqual({ people, firsts })
        expect(logic.values.detailsError).toBeNull()
        logic.unmount()
    })
    it('retries a failed people expansion without replacing loaded previews', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts,
            matrix: BOOK_ACTIVITY_MATRIX_MOCK,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        const accountId = BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key
        const productKey = 'pa'
        const key = JSON.stringify([accountId, productKey])
        const person = {
            row: accountId,
            column: BOOK_ACTIVITY_MATRIX_MOCK.columns[0].key,
            series: productKey,
            personId: 'example-person',
            label: 'person@example.com',
            rank: 1,
            engagedSeconds: 120,
            actionCount: 1,
            actions: [],
            topPaths: [],
        }
        const previews = {
            rows: BOOK_ACTIVITY_MATRIX_MOCK.rows.slice(0, 5),
            columns: BOOK_ACTIVITY_MATRIX_MOCK.columns,
            people: [person],
            truncated: false,
        }
        query.mockResolvedValueOnce({ results: previews })
        await expectLogic(logic, () => logic.actions.setControls({ zoom: 'users' })).toFinishAllListeners()
        query.mockRejectedValueOnce(new Error('Expansion unavailable'))
        await expectLogic(logic, () => logic.actions.togglePeople(accountId, productKey)).toFinishAllListeners()
        expect(logic.values.peopleError).toEqual({ key, message: 'Expansion unavailable' })
        expect(logic.values.expanded[key]).toBe(false)
        const expandedPeople = [
            person,
            { ...person, personId: 'another-person', label: 'another@example.com', rank: 2 },
        ]
        let resolve!: (value: unknown) => void
        query.mockImplementationOnce((node) => {
            if (!node.allPeople || node.accountIds[0] !== accountId || node.productKeys[0] !== productKey) {
                return Promise.reject(new Error('Retry must reload the failed expansion'))
            }
            return new Promise((done) => {
                resolve = done
            })
        })
        logic.actions.retryDetails()
        expect(logic.values.detailsRetryLoading).toBe(true)
        expect(logic.values.details.people).toEqual(previews)
        resolve({ results: { ...previews, people: expandedPeople } })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.extraPeople[key]).toEqual(expandedPeople)
        expect(logic.values.expanded[key]).toBe(true)
        expect(logic.values.peopleError).toBeNull()
        expect(logic.values.detailsRetryLoading).toBe(false)
        expect(logic.values.details.people).toEqual(previews)
        logic.unmount()
    })
    it('clears pending people state when leaving Users or clearing the source', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts,
            matrix: BOOK_ACTIVITY_MATRIX_MOCK,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        let resolve!: (value: unknown) => void
        query.mockImplementation(
            () =>
                new Promise((done) => {
                    resolve = done
                })
        )
        logic.actions.setControls({ zoom: 'users' })
        expect(logic.values.detailsLoading).toBe(true)
        logic.actions.setControls({ zoom: 'products' })
        expect(logic.values.detailsLoading).toBe(false)
        resolve({ results: { people: [], rows: [], columns: [], truncated: false } })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.details).toEqual({ people: null, firsts: null })
        logic.actions.setControls({ zoom: 'users' })
        expect(logic.values.detailsLoading).toBe(true)
        logic.actions.clearSource()
        expect(logic.values.detailsLoading).toBe(false)
        resolve({ results: { people: [], rows: [], columns: [], truncated: false } })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.details).toEqual({ people: null, firsts: null })
        expect(logic.values.result).toBeNull()
        logic.unmount()
    })
    it('cancels server history queries on opt-out and all detail queries on unmount', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        const teamId = logic.values.currentTeamId
        logic.actions.finishLoad({
            accounts,
            matrix: BOOK_ACTIVITY_MATRIX_MOCK,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        const resolves: ((value: unknown) => void)[] = []
        query.mockImplementation(() => new Promise((resolve) => resolves.push(resolve)))
        logic.actions.setControls({ firstUse: true })
        const firstsRequest = query.mock.calls[0]
        expect(firstsRequest[0].kind).toBe(NodeKind.BookActivityFirstsQuery)
        expect(firstsRequest[3]).toEqual(expect.any(String))
        logic.actions.setControls({ firstUse: false })
        expect(firstsRequest[1].signal.aborted).toBe(true)
        expect(cancelQueryOnServer).toHaveBeenCalledWith(teamId, firstsRequest[3])
        resolves.shift()!({ results: { accounts: [], people: [], truncated: false } })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setControls({ zoom: 'users', firstUse: true })
        logic.actions.togglePeople(BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key, BOOK_ACTIVITY_MATRIX_MOCK.series[0].key)
        const activeRequests = query.mock.calls.slice(1)
        expect(activeRequests).toHaveLength(3)
        expect(new Set(activeRequests.map((call) => call[3])).size).toBe(3)
        logic.unmount()
        for (const call of activeRequests) {
            expect(call[3]).toEqual(expect.any(String))
            expect(call[1].signal.aborted).toBe(true)
            expect(cancelQueryOnServer).toHaveBeenCalledWith(teamId, call[3])
        }
        for (const resolve of resolves) {
            resolve({ results: { accounts: [], people: [], truncated: false } })
        }
        await expectLogic(logic).toFinishAllListeners()
    })
    it('records safe query outcomes and keeps errors out of event properties', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        query.mockRejectedValueOnce(Object.assign(new Error('sensitive query text'), { status: 400 }))
        await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['failLoad'])
        expect(posthog.capture).toHaveBeenCalledWith('customer analytics product activity query failed', {
            source_kind: 'hogql',
            status_code: 400,
        })
        expect(posthog.capture).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ query: sql }))
        logic.unmount()
    })
    it('retains clicked account focus and restores only bounded URL controls', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts,
            matrix: {
                ...BOOK_ACTIVITY_MATRIX_MOCK,
                rows: Array.from({ length: 12 }, (_, index) => ({
                    key: String(index),
                    label: `Account ${index}`,
                    externalId: `org-${index}`,
                })),
            },
            hogql: null,
            source: { kind: 'product_usage' },
        })
        query.mockResolvedValue({ results: { people: [], rows: [], columns: [], truncated: false } })
        logic.actions.zoomToCell('8', '2026-10-05')
        expect(logic.values.userPage).toBe(2)
        expect(logic.values.focusedCell).toEqual({ accountId: '8', columnKey: '2026-10-05' })
        const parsed = parseProductUsageControls(
            { zoom: 'users', openProducts: [JSON.stringify(['8', 'pa'])], query: 'private SQL' },
            logic.values.controls
        )
        expect(parsed.openProducts).toEqual([JSON.stringify(['8', 'pa'])])
        expect(parsed).not.toHaveProperty('query')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
    })
    it('limits restored full people queries to visible accounts and aborts them when cleared', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts,
            matrix: {
                ...BOOK_ACTIVITY_MATRIX_MOCK,
                rows: Array.from({ length: 6 }, (_, index) => ({
                    key: String(index),
                    label: `Account ${index}`,
                    externalId: `org-${index}`,
                })),
            },
            hogql: null,
            source: { kind: 'product_usage' },
        })
        const resolves: ((value: unknown) => void)[] = []
        query.mockImplementation(() => new Promise((resolve) => resolves.push(resolve)))
        const product = BOOK_ACTIVITY_MATRIX_MOCK.series[0].key
        logic.actions.setControls({
            zoom: 'users',
            openProducts: Array.from({ length: 6 }, (_, index) => JSON.stringify([String(index), product])),
        })
        const fullCalls = query.mock.calls.filter(([request]) => request.allPeople)
        expect(fullCalls).toHaveLength(3)
        expect(fullCalls.map(([request]) => request.accountIds)).toEqual([['0'], ['1'], ['2']])
        const preview = query.mock.calls.find(
            ([request]) => request.kind === NodeKind.BookActivityPeopleQuery && !request.allPeople
        )
        expect(preview?.[0].accountIds).toEqual(['0', '1', '2', '3', '4'])
        logic.actions.setUserPage(2)
        expect(fullCalls.every(([, options]) => options.signal.aborted)).toBe(true)
        expect(
            query.mock.calls.filter(([request]) => request.allPeople).map(([request]) => request.accountIds)
        ).toEqual([['0'], ['1'], ['2'], ['5']])
        expect(
            query.mock.calls
                .filter(([request]) => request.kind === NodeKind.BookActivityPeopleQuery && !request.allPeople)
                .at(-1)?.[0].accountIds
        ).toEqual(['5'])
        logic.actions.clearSource()
        expect(fullCalls.every(([, options]) => options.signal.aborted)).toBe(true)
        for (const resolve of resolves) {
            resolve({ results: { people: [], rows: [], columns: [], truncated: false } })
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.extraPeople).toEqual({})
        expect(logic.values.peopleLoading).toEqual({})
        logic.unmount()
    })
    it('does not run custom SQL when no accounts match, and ignores a canceled response', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.openEditor('hogql')
        logic.actions.setQueryDraft(sql)
        query.mockResolvedValueOnce({ results: [], hasMore: false })
        await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['finishLoad'])
        expect(query).toHaveBeenCalledTimes(1)
        let resolve!: (value: unknown) => void
        query.mockImplementationOnce(
            () =>
                new Promise((done) => {
                    resolve = done
                })
        )
        logic.actions.runQuery()
        const accountQueryId = query.mock.calls[query.mock.calls.length - 1][3]
        logic.actions.cancelEditor()
        expect(cancelQueryOnServer).toHaveBeenCalledWith(logic.values.currentTeamId, accountQueryId)
        resolve(accounts)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.result).toBeNull()
        expect(logic.values.source).toBeNull()
        logic.unmount()
    })
})
