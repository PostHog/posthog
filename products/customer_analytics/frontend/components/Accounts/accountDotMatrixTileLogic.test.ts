import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

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

    describe('keeping the saved source until save', () => {
        const SAVED_SQL = {
            kind: 'hogql',
            query: 'SELECT event AS r, 1 AS c',
            mapping: { row: 'r', column: 'c' },
        } as const
        const SQL_RESPONSE = { columns: ['r', 'c'], results: [['saved', 1]] }
        const DRAFT_RESPONSE = { columns: ['r', 'c'], results: [['draft', 1]] }
        const dialog = jest.spyOn(LemonDialog, 'open')

        beforeEach(() => {
            dialog.mockReset()
        })

        it.each([
            ['product usage', { source: { kind: 'product_usage' } }, BOOK_ACTIVITY_MATRIX_MOCK],
            ['account activity', { source: { kind: 'usage_metrics' } }, EMPTY_ACCOUNT_ACTIVITY_MATRIX],
            ['a legacy tile', { selectedSeries: [] }, EMPTY_ACCOUNT_ACTIVITY_MATRIX],
        ])('picking Custom HogQL on %s saves nothing, and Cancel keeps its results', async (_, config, results) => {
            mockPerformQuery.mockResolvedValue({ results })
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'pick-sql',
                accountId: 'account-1',
                initialConfig: config,
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            const savedConfig = logic.values.config
            const savedResult = logic.values.matrixResult
            expect(savedResult).not.toBeNull()

            await expectLogic(logic, () => logic.actions.chooseSource('hogql')).toFinishAllListeners()

            expect(save).not.toHaveBeenCalled()
            expect(logic.values.config).toEqual(savedConfig)
            expect(logic.values.queryEditorOpen).toBe(true)
            expect(logic.values.sourceKind).toBe('hogql')

            await expectLogic(logic, () => logic.actions.cancelQuery()).toFinishAllListeners()

            expect(save).not.toHaveBeenCalled()
            expect(logic.values.queryEditorOpen).toBe(false)
            expect(logic.values.config).toEqual(savedConfig)
            expect(logic.values.matrixResult).toEqual(savedResult)
            expect(mockPerformQuery).toHaveBeenCalledTimes(1)
            logic.unmount()
        })

        it('returns a new tile to the source picker on Cancel', async () => {
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'new-cancel',
                accountId: 'account-1',
                initialConfig: { source: null },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic, () => logic.actions.chooseSource('hogql')).toFinishAllListeners()
            mockPerformQuery.mockResolvedValue(DRAFT_RESPONSE)
            logic.actions.setMappingDraft({ row: 'r', column: 'c' })
            await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['loadMatrixSuccess'])

            await expectLogic(logic, () => logic.actions.cancelQuery()).toFinishAllListeners()

            expect(save).not.toHaveBeenCalled()
            expect(logic.values.sourceKind).toBeNull()
            expect(logic.values.matrixResult).toBeNull()
            logic.unmount()
        })

        it('asks before a preset replaces saved SQL, and leaves it alone until confirmed', async () => {
            mockPerformQuery.mockResolvedValue(SQL_RESPONSE)
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'replace-sql',
                accountId: 'account-1',
                initialConfig: { source: SAVED_SQL },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            const queries = mockPerformQuery.mock.calls.length

            await expectLogic(logic, () => logic.actions.chooseSource('product_usage')).toFinishAllListeners()

            expect(dialog).toHaveBeenCalledTimes(1)
            expect(save).not.toHaveBeenCalled()
            expect(logic.values.config.source).toEqual(SAVED_SQL)
            expect(mockPerformQuery).toHaveBeenCalledTimes(queries)

            mockPerformQuery.mockResolvedValue({ results: BOOK_ACTIVITY_MATRIX_MOCK })
            const primary = dialog.mock.calls[0][0].primaryButton
            await expectLogic(logic, () => primary?.onClick?.({} as any)).toDispatchActions(['loadMatrixSuccess'])

            expect(logic.values.config.source).toEqual({ kind: 'product_usage' })
            expect(save).toHaveBeenLastCalledWith(expect.objectContaining({ source: { kind: 'product_usage' } }))
            expect(logic.values.matrixResult?.kind).toBe('product_usage')
            logic.unmount()
        })

        it('switches between presets without asking, since no SQL is lost', async () => {
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'preset-switch',
                accountId: 'account-1',
                initialConfig: { source: { kind: 'usage_metrics' } },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            mockPerformQuery.mockResolvedValue({ results: BOOK_ACTIVITY_MATRIX_MOCK })

            await expectLogic(logic, () => logic.actions.chooseSource('product_usage')).toDispatchActions([
                'loadMatrixSuccess',
            ])

            expect(dialog).not.toHaveBeenCalled()
            expect(logic.values.config.source).toEqual({ kind: 'product_usage' })
            logic.unmount()
        })

        it('opens saved SQL when Custom HogQL is picked again, without resetting it', async () => {
            mockPerformQuery.mockResolvedValue(SQL_RESPONSE)
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'repick-sql',
                accountId: 'account-1',
                initialConfig: { source: SAVED_SQL },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()

            await expectLogic(logic, () => logic.actions.chooseSource('hogql')).toFinishAllListeners()

            expect(save).not.toHaveBeenCalled()
            expect(logic.values.queryDraft).toBe(SAVED_SQL.query)
            expect(logic.values.mappingDraft).toEqual(SAVED_SQL.mapping)
            expect(logic.values.matrixResult).toMatchObject({ kind: 'hogql', query: SAVED_SQL.query })
            logic.unmount()
        })

        it('restores the saved query and its results when Cancel follows a draft run', async () => {
            mockPerformQuery.mockResolvedValue(SQL_RESPONSE)
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'cancel-draft',
                accountId: 'account-1',
                initialConfig: { source: SAVED_SQL },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()

            logic.actions.editQuery()
            logic.actions.setQueryDraft('SELECT event AS r, 2 AS c')
            mockPerformQuery.mockResolvedValue(DRAFT_RESPONSE)
            await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['loadMatrixSuccess'])
            expect(logic.values.matrixResult).toMatchObject({ query: 'SELECT event AS r, 2 AS c' })

            mockPerformQuery.mockResolvedValue(SQL_RESPONSE)
            await expectLogic(logic, () => logic.actions.cancelQuery()).toDispatchActions(['loadMatrixSuccess'])

            expect(save).not.toHaveBeenCalled()
            expect(logic.values.config.source).toEqual(SAVED_SQL)
            expect(logic.values.queryEditorOpen).toBe(false)
            expect(logic.values.matrixResult).toMatchObject({ kind: 'hogql', query: SAVED_SQL.query })

            logic.actions.editQuery()
            expect(logic.values.queryDraft).toBe(SAVED_SQL.query)
            logic.unmount()
        })

        it('asks before picking a preset discards an edited draft on a preset tile', async () => {
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'discard-draft',
                accountId: 'account-1',
                initialConfig: { source: { kind: 'usage_metrics' } },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            logic.actions.chooseSource('hogql')
            logic.actions.setQueryDraft('SELECT 1')

            await expectLogic(logic, () => logic.actions.chooseSource('usage_metrics')).toFinishAllListeners()

            expect(dialog).toHaveBeenCalledTimes(1)
            expect(logic.values.queryEditorOpen).toBe(true)
            expect(logic.values.queryDraft).toBe('SELECT 1')
            logic.unmount()
        })

        it('hides saved preset results while a new query is being written', async () => {
            mockPerformQuery.mockResolvedValue({ results: BOOK_ACTIVITY_MATRIX_MOCK })
            const logic = accountDotMatrixTileLogic({
                instanceId: 'preset-hidden',
                accountId: 'account-1',
                initialConfig: { source: { kind: 'product_usage' } },
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            expect(logic.values.displayResult?.kind).toBe('product_usage')

            logic.actions.chooseSource('hogql')
            expect(logic.values.displayResult).toBeNull()

            logic.actions.cancelQuery()
            expect(logic.values.displayResult?.kind).toBe('product_usage')
            logic.unmount()
        })

        it('keeps legend clicks on a draft out of the saved view', async () => {
            mockPerformQuery.mockResolvedValue(SQL_RESPONSE)
            const save = jest.fn()
            const logic = accountDotMatrixTileLogic({
                instanceId: 'draft-selection',
                accountId: 'account-1',
                initialConfig: { source: SAVED_SQL, selectedSeries: ['kept'] },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            logic.actions.editQuery()

            logic.actions.setSelectedSeries(['draft-only'])
            expect(save).not.toHaveBeenCalled()

            await expectLogic(logic, () => logic.actions.cancelQuery()).toFinishAllListeners()
            expect(logic.values.config.selectedSeries).toEqual(['kept'])
            logic.unmount()
        })
    })

    describe('changing weeks while editing', () => {
        const DRAFT = 'SELECT person AS who, week AS wk FROM events'
        const MAPPING = { row: 'who', column: 'wk' }
        const RESPONSE = { columns: ['who', 'wk'], results: [['person-1', 'week-1']] }
        const lastQuery = (): any => mockPerformQuery.mock.calls[mockPerformQuery.mock.calls.length - 1][0]

        async function mountWithRunDraft(save: jest.Mock): Promise<ReturnType<typeof accountDotMatrixTileLogic>> {
            const logic = accountDotMatrixTileLogic({
                instanceId: 'weeks-draft',
                accountId: 'account-1',
                externalId: 'external-1',
                initialConfig: { source: null },
                onConfigChange: save,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.chooseSource('hogql')
            logic.actions.setQueryDraft(DRAFT)
            logic.actions.setMappingDraft(MAPPING)
            mockPerformQuery.mockResolvedValue(RESPONSE)
            await expectLogic(logic, () => logic.actions.runQuery()).toDispatchActions(['loadMatrixSuccess'])
            return logic
        }

        it('keeps results and mapping, and re-runs the executed query for the new window', async () => {
            const save = jest.fn()
            const logic = await mountWithRunDraft(save)
            let resolveRerun: (value: unknown) => void = () => {}
            mockPerformQuery.mockImplementationOnce(() => new Promise((resolve) => (resolveRerun = resolve)))

            logic.actions.setWeeks(12)

            expect(logic.values.matrixResult).toMatchObject({ kind: 'hogql', query: DRAFT })
            expect(logic.values.mappingDraft).toEqual(MAPPING)
            expect(lastQuery()).toMatchObject({ query: DRAFT, filters: { dateRange: { date_from: '-11wStart' } } })

            resolveRerun(RESPONSE)
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()

            expect(logic.values.queryEditorOpen).toBe(true)
            expect(logic.values.mappingDraft).toEqual(MAPPING)
            expect(logic.values.querySaveError).toBeNull()
            expect(logic.values.presentation.matrix.data).toHaveLength(1)
            expect(save).toHaveBeenLastCalledWith({ mode: 'dots', weeks: 12, selectedSeries: [], source: null })
            logic.unmount()
        })

        it('re-runs what was executed, never unrun edits in the editor', async () => {
            const logic = await mountWithRunDraft(jest.fn())
            logic.actions.setQueryDraft('SELECT unrun edits')

            await expectLogic(logic, () => logic.actions.setWeeks(26)).toFinishAllListeners()

            expect(lastQuery().query).toBe(DRAFT)
            expect(logic.values.queryDraft).toBe('SELECT unrun edits')
            expect(logic.values.querySaveError).toBe('Run the query before saving.')
            logic.unmount()
        })

        it('runs nothing when no query has run yet', async () => {
            const logic = accountDotMatrixTileLogic({
                instanceId: 'weeks-unrun',
                accountId: 'account-1',
                initialConfig: { source: null },
            })
            logic.mount()
            logic.actions.chooseSource('hogql')

            await expectLogic(logic, () => logic.actions.setWeeks(12)).toFinishAllListeners()

            expect(mockPerformQuery).not.toHaveBeenCalled()
            logic.unmount()
        })

        it('supersedes a run still in flight, keeping that query', async () => {
            const logic = accountDotMatrixTileLogic({
                instanceId: 'weeks-inflight',
                accountId: 'account-1',
                externalId: 'external-1',
                initialConfig: { source: null },
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.chooseSource('hogql')
            logic.actions.setQueryDraft(DRAFT)
            logic.actions.setMappingDraft(MAPPING)
            let releaseFirstRun: (value: unknown) => void = () => {}
            mockPerformQuery.mockImplementationOnce(() => new Promise((resolve) => (releaseFirstRun = resolve)))
            logic.actions.runQuery()
            mockPerformQuery.mockResolvedValue(RESPONSE)

            logic.actions.setWeeks(12)
            releaseFirstRun(RESPONSE)
            await expectLogic(logic).toFinishAllListeners()

            expect(lastQuery()).toMatchObject({ query: DRAFT, filters: { dateRange: { date_from: '-11wStart' } } })
            expect(logic.values.matrixResult).toMatchObject({ query: DRAFT })
            logic.unmount()
        })

        it('reloads the saved results on Cancel for the new window', async () => {
            mockPerformQuery.mockResolvedValue({ results: BOOK_ACTIVITY_MATRIX_MOCK })
            const logic = accountDotMatrixTileLogic({
                instanceId: 'weeks-preset',
                accountId: 'account-1',
                initialConfig: { source: { kind: 'product_usage' } },
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadMatrixSuccess']).toFinishAllListeners()
            logic.actions.chooseSource('hogql')

            await expectLogic(logic, () => logic.actions.setWeeks(12)).toDispatchActions(['loadMatrixSuccess'])
            logic.actions.cancelQuery()

            expect(lastQuery()).toMatchObject({ dateRange: { date_from: '-11wStart' } })
            expect(logic.values.displayResult?.kind).toBe('product_usage')
            logic.unmount()
        })
    })
})
