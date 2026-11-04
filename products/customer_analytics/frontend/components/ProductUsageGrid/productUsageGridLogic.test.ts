import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { NodeKind, type AccountsTableQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../Accounts/bookActivityMatrixMock'
import { parseProductUsageControls } from './productUsageControls'
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
        query.mockReset()
        jest.spyOn(posthog, 'capture').mockClear()
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
                    externalId: null,
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
                    externalId: null,
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
