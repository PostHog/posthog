import { FunnelLayout } from 'lib/constants'
import { getConfig } from 'scenes/insights/views/Histogram/histogramUtils'

import { initKeaTests } from '~/test/init'

import { histogramLogic } from './histogramLogic'

describe('histogramLogic', () => {
    let logic: ReturnType<typeof histogramLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = histogramLogic()
        logic.mount()
    })

    describe('values', () => {
        it('has proper defaults', () => {
            expect(logic.values).toMatchSnapshot()
        })
    })

    describe('reducers', () => {
        describe('config', () => {
            it('is set via setConfig', async () => {
                const newConfig = getConfig(FunnelLayout.vertical, 1000, 3000)
                expect(logic.values.config).toEqual(getConfig(FunnelLayout.vertical))
                logic.actions.setConfig(newConfig)
                expect(logic.values.config).toEqual(newConfig)
            })
        })
    })
})
