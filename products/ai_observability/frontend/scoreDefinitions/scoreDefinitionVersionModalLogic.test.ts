import { initKeaTests } from '~/test/init'

import { scoreDefinitionVersionModalLogic } from './scoreDefinitionVersionModalLogic'

describe('scoreDefinitionVersionModalLogic', () => {
    beforeEach(() => initKeaTests())

    it('keeps launchers independent and closes the modal when its launcher unmounts', () => {
        const first = scoreDefinitionVersionModalLogic({ instanceKey: 'list-row' })
        const second = scoreDefinitionVersionModalLogic({ instanceKey: 'history-button' })
        const unmountFirst = first.mount()
        const unmountSecond = second.mount()

        first.actions.openModal()
        expect(first.values.isOpen).toBe(true)
        expect(second.values.isOpen).toBe(false)

        second.actions.openModal()
        first.actions.closeModal()
        expect(first.values.isOpen).toBe(false)
        expect(second.values.isOpen).toBe(true)

        unmountSecond()
        const remounted = scoreDefinitionVersionModalLogic({ instanceKey: 'history-button' })
        const unmountRemounted = remounted.mount()
        expect(remounted.values.isOpen).toBe(false)

        unmountFirst()
        unmountRemounted()
    })
})
