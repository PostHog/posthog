import { expectLogic } from 'kea-test-utils'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { EMPTY_ACCOUNT_ACTIVITY_MATRIX } from './accountActivityMatrix'
import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { BOOK_ACTIVITY_MATRIX_MOCK } from './bookActivityMatrixMock'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({
    ...jest.requireActual('~/queries/nodes/DataNode/dataNodeLogic'),
    cancelQueryOnServer: jest.fn(),
}))
const mockPerformQuery = performQuery as jest.Mock

describe('accountDotMatrixTileLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockPerformQuery.mockReset()
        ;(cancelQueryOnServer as jest.Mock).mockReset()
        mockPerformQuery.mockResolvedValue({ results: EMPTY_ACCOUNT_ACTIVITY_MATRIX })
    })

    it('queries activity for its own account and reloads when the week window changes', async () => {
        const onConfigChange = jest.fn()
        const logic = accountDotMatrixTileLogic({ instanceId: 'tile-one', accountId: 'account-1', onConfigChange })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMatrixSuccess'])

        await expectLogic(logic, () => logic.actions.setWeeks(12)).toDispatchActions(['loadMatrixSuccess'])

        expect(mockPerformQuery.mock.calls.map(([query]) => query)).toEqual([
            { kind: NodeKind.AccountActivityMatrixQuery, accountId: 'account-1', weeks: 8 },
            { kind: NodeKind.AccountActivityMatrixQuery, accountId: 'account-1', weeks: 12 },
        ])
        expect(onConfigChange).toHaveBeenLastCalledWith({ mode: 'dots', weeks: 12, selectedSeries: [] })
        logic.unmount()
    })

    it('waits for a source, scopes product usage, and reuses data for display and selection', async () => {
        const save = jest.fn()
        const logic = accountDotMatrixTileLogic({
            instanceId: 'new',
            accountId: 'account-1',
            initialConfig: { source: null },
            onConfigChange: save,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPerformQuery).not.toHaveBeenCalled()
        mockPerformQuery.mockResolvedValue({ results: BOOK_ACTIVITY_MATRIX_MOCK })
        await expectLogic(logic, () => logic.actions.chooseSource('product_usage')).toDispatchActions([
            'loadMatrixSuccess',
        ])
        expect(mockPerformQuery.mock.calls[0][0]).toEqual({
            kind: NodeKind.BookActivityMatrixQuery,
            accountIds: ['account-1'],
            dateRange: { date_from: '-7wStart', date_to: null },
            interval: 'week',
            includeFirstUse: false,
        })
        logic.actions.setMode('count')
        logic.actions.setSelectedSeries(['pa', 'replay'])
        expect(mockPerformQuery).toHaveBeenCalledTimes(1)
        expect(save).toHaveBeenLastCalledWith({
            mode: 'count',
            weeks: 8,
            selectedSeries: ['pa', 'replay'],
            source: { kind: 'product_usage' },
        })
        logic.unmount()
    })

    it('runs SQL explicitly and saves only a mapping for the executed draft', async () => {
        const save = jest.fn()
        const logic = accountDotMatrixTileLogic({
            instanceId: 'sql',
            accountId: 'account-1',
            initialConfig: { source: null },
            onConfigChange: save,
        })
        logic.mount()
        logic.actions.chooseSource('hogql')
        logic.actions.setQueryDraft('SELECT {account_id} AS who, 1 AS period')
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPerformQuery).not.toHaveBeenCalled()
        mockPerformQuery.mockResolvedValue({ columns: ['who', 'period'], results: [['account-1', 1]] })
        await expectLogic(logic, () => logic.actions.runQuery())
            .toDispatchActions(['loadMatrixSuccess'])
            .toFinishAllListeners()
            .toMatchValues({ matrixResultLoading: false })
        logic.actions.saveQuery()
        expect(logic.values.config.source).toBeNull()
        logic.actions.setMappingDraft({ row: 'who', column: 'period' })
        expect(logic.values.querySaveError).toBeNull()
        await expectLogic(logic, () => logic.actions.saveQuery()).toDispatchActions(['applyQuery'])
        const saved = logic.values.config
        expect(saved.source).toEqual({
            kind: 'hogql',
            query: 'SELECT {account_id} AS who, 1 AS period',
            mapping: { row: 'who', column: 'period' },
        })
        expect(save).toHaveBeenLastCalledWith(saved)
        expect(mockPerformQuery).toHaveBeenCalledTimes(1)
        logic.actions.editQuery()
        logic.actions.setQueryDraft('SELECT 2')
        expect(logic.values.querySaveError).toBe('Run the query before saving.')
        logic.actions.saveQuery()
        expect(logic.values.config).toEqual(saved)
        logic.unmount()
        const restored = accountDotMatrixTileLogic({
            instanceId: 'sql',
            accountId: 'account-2',
            initialConfig: { ...saved },
        })
        restored.mount()
        await expectLogic(restored).toDispatchActions(['loadMatrixSuccess'])
        expect(mockPerformQuery.mock.calls[1][0]).toMatchObject({
            kind: NodeKind.HogQLQuery,
            values: { account_id: 'account-2' },
        })
        restored.unmount()
    })

    it('cancels a request when switching to an unconfigured SQL source and ignores late success', async () => {
        let finish: (value: unknown) => void = () => {}
        let signal: AbortSignal | undefined
        mockPerformQuery.mockImplementationOnce(
            (_query, options) =>
                new Promise((resolve) => {
                    finish = resolve
                    signal = options.signal
                })
        )
        const logic = accountDotMatrixTileLogic({ instanceId: 'cancel', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.chooseSource('hogql')).toDispatchActions(['loadMatrixSuccess'])
        finish({ results: EMPTY_ACCOUNT_ACTIVITY_MATRIX })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.matrixResult).toBeNull()
        expect(logic.values.loadError).toBeNull()
        expect(signal?.aborted).toBe(true)
        expect(cancelQueryOnServer).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('persists each instance independently and restores its saved config on remount', async () => {
        const saveFirst = jest.fn()
        const saveSecond = jest.fn()
        const first = accountDotMatrixTileLogic({
            instanceId: 'one',
            accountId: 'account-1',
            onConfigChange: saveFirst,
        })
        const second = accountDotMatrixTileLogic({
            instanceId: 'two',
            accountId: 'account-1',
            onConfigChange: saveSecond,
        })
        first.mount()
        second.mount()
        first.actions.setSelectedSeries(['metric-replay'])
        second.actions.setMode('count')
        expect(saveFirst).toHaveBeenLastCalledWith({ mode: 'dots', weeks: 8, selectedSeries: ['metric-replay'] })
        expect(saveSecond).toHaveBeenLastCalledWith({ mode: 'count', weeks: 8, selectedSeries: [] })
        const saved = second.values.config
        second.unmount()
        const restored = accountDotMatrixTileLogic({
            instanceId: 'two',
            accountId: 'account-1',
            initialConfig: { ...saved },
        })
        restored.mount()
        expect(restored.values.config).toEqual(saved)
        first.unmount()
        restored.unmount()
    })

    it('reports a failed load as a failure, not as an empty matrix, and retries', async () => {
        mockPerformQuery.mockRejectedValueOnce(Object.assign(new Error('boom'), { status: 500 }))
        const logic = accountDotMatrixTileLogic({ instanceId: 'failing', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMatrixFailure']).toMatchValues({
            loadError: 'boom',
        })

        await expectLogic(logic, () => logic.actions.retry())
            .toDispatchActions(['loadMatrixSuccess'])
            .toMatchValues({ loadError: null })
        expect(mockPerformQuery).toHaveBeenCalledTimes(2)
        logic.unmount()
    })

    it('aborts a superseded request and ignores its late failure', async () => {
        const superseded: { signal?: AbortSignal; reject?: (error: unknown) => void } = {}
        mockPerformQuery.mockImplementationOnce(
            (_query, options) =>
                new Promise((_resolve, reject) => {
                    superseded.signal = options.signal
                    superseded.reject = reject
                })
        )
        const logic = accountDotMatrixTileLogic({ instanceId: 'superseded', accountId: 'account-1' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.setWeeks(12)).toDispatchActions(['loadMatrixSuccess'])
        superseded.reject?.(Object.assign(new Error('boom'), { status: 500 }))

        await expectLogic(logic)
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['loadMatrixFailure'])
            .toMatchValues({ loadError: null })
        expect(superseded.signal?.aborted).toBe(true)
        expect(cancelQueryOnServer).toHaveBeenCalledTimes(1)
        logic.unmount()
    })
})
