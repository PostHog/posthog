import { resetContext } from 'kea'

import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'

describe('accountDotMatrixTileLogic', () => {
    beforeEach(() => resetContext())

    it('persists each instance independently and restores its saved config on remount', () => {
        const saveFirst = jest.fn()
        const saveSecond = jest.fn()
        const first = accountDotMatrixTileLogic({ instanceId: 'people-one', onConfigChange: saveFirst })
        const second = accountDotMatrixTileLogic({ instanceId: 'ci-two', onConfigChange: saveSecond })
        first.mount()
        second.mount()
        first.actions.setSelectedSeries(['replay'])
        second.actions.setDataset('ci')
        second.actions.setMode('count')
        expect(first.values.config).toEqual({ dataset: 'people', mode: 'dots', selectedSeries: ['replay'] })
        expect(saveFirst).toHaveBeenLastCalledWith(first.values.config)
        expect(saveSecond).toHaveBeenLastCalledWith({ dataset: 'ci', mode: 'count', selectedSeries: [] })
        const saved = second.values.config
        second.unmount()
        const restored = accountDotMatrixTileLogic({ instanceId: 'ci-two', initialConfig: { ...saved } })
        restored.mount()
        expect(restored.values.config).toEqual(saved)
        first.unmount()
        restored.unmount()
    })

    it('clears selections when changing datasets', () => {
        const onConfigChange = jest.fn()
        const logic = accountDotMatrixTileLogic({ instanceId: 'dataset-change', onConfigChange })
        logic.mount()
        logic.actions.setSelectedSeries(['replay'])
        logic.actions.setDataset('ci')
        expect(logic.values.config.selectedSeries).toEqual([])
        expect(onConfigChange).toHaveBeenLastCalledWith({ dataset: 'ci', mode: 'dots', selectedSeries: [] })
        logic.unmount()
    })
})
