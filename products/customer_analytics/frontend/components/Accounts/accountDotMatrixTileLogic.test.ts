import { expectLogic } from 'kea-test-utils'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { EMPTY_ACCOUNT_ACTIVITY_MATRIX } from './accountActivityMatrix'
import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'

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
        await expectLogic(logic).toDispatchActions(['loadAccountActivityMatrixSuccess'])

        await expectLogic(logic, () => logic.actions.setWeeks(12)).toDispatchActions([
            'loadAccountActivityMatrixSuccess',
        ])

        expect(mockPerformQuery.mock.calls.map(([query]) => query)).toEqual([
            { kind: NodeKind.AccountActivityMatrixQuery, accountId: 'account-1', weeks: 8 },
            { kind: NodeKind.AccountActivityMatrixQuery, accountId: 'account-1', weeks: 12 },
        ])
        expect(onConfigChange).toHaveBeenLastCalledWith({ mode: 'dots', weeks: 12, selectedSeries: [] })
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
        await expectLogic(logic).toDispatchActions(['loadAccountActivityMatrixFailure']).toMatchValues({
            loadFailed: true,
        })

        await expectLogic(logic, () => logic.actions.retry())
            .toDispatchActions(['loadAccountActivityMatrixSuccess'])
            .toMatchValues({ loadFailed: false })
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

        await expectLogic(logic, () => logic.actions.setWeeks(12)).toDispatchActions([
            'loadAccountActivityMatrixSuccess',
        ])
        superseded.reject?.(Object.assign(new Error('boom'), { status: 500 }))

        await expectLogic(logic)
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['loadAccountActivityMatrixFailure'])
            .toMatchValues({ loadFailed: false })
        expect(superseded.signal?.aborted).toBe(true)
        expect(cancelQueryOnServer).toHaveBeenCalledTimes(1)
        logic.unmount()
    })
})
