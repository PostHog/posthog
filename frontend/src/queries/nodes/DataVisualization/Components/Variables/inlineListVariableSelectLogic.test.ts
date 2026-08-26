import { initKeaTests } from '~/test/init'

import { inlineListVariableSelectLogic } from './inlineListVariableSelectLogic'

describe('inlineListVariableSelectLogic', () => {
    let logic: ReturnType<typeof inlineListVariableSelectLogic.build>
    let onChange: jest.Mock

    beforeEach(() => {
        initKeaTests()
        onChange = jest.fn()
        logic = inlineListVariableSelectLogic({
            variableId: 'variable-id',
            selectedValues: [],
            onChange,
        })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('commits several option changes once when the selection closes', () => {
        logic.actions.setSelectedValues(['pageview'])
        logic.actions.setSelectedValues(['pageview', 'signup'])
        inlineListVariableSelectLogic({
            variableId: 'variable-id',
            selectedValues: [],
            onChange,
        })

        expect(logic.values.selectedValues).toEqual(['pageview', 'signup'])
        expect(onChange).not.toHaveBeenCalled()

        logic.actions.commitSelectedValues()
        logic.actions.commitSelectedValues()

        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange).toHaveBeenCalledWith(['pageview', 'signup'])
    })
})
