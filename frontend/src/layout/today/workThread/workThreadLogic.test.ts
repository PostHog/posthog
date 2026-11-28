import { initKeaTests } from '~/test/init'

import { checkoutWorkThread, finishedWorkThread } from './workThreadFixtures'
import { workThreadLogic } from './workThreadLogic'

describe('workThreadLogic', () => {
    let logic: ReturnType<typeof workThreadLogic.build>

    beforeEach(() => {
        initKeaTests(false)
        logic = workThreadLogic({ threadKey: checkoutWorkThread.key })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test('an expand override is kept per step and a later override replaces it', () => {
        logic.actions.setStepExpanded('release-planned', true)
        logic.actions.setStepExpanded('experiment-result', false)
        logic.actions.setStepExpanded('release-planned', false)

        expect(logic.values.expandedOverrides).toEqual({ 'release-planned': false, 'experiment-result': false })
    })

    test.each([
        ['opening another option', () => logic.actions.openOption('experiment-result', 'extend-week')],
        ['closing the option', () => logic.actions.closeOption()],
    ])('the prompt view resets on %s', (_name, act) => {
        logic.actions.openOption('experiment-result', 'ship-winner')
        logic.actions.setPromptShown(true)
        expect(logic.values.promptShown).toBe(true)

        act()

        expect(logic.values.promptShown).toBe(false)
    })

    test('opening an option records it and closing it clears it', () => {
        logic.actions.openOption('experiment-result', 'ship-winner')
        expect(logic.values.openOptionRef).toEqual({ stepKey: 'experiment-result', optionKey: 'ship-winner' })

        logic.actions.closeOption()
        expect(logic.values.openOptionRef).toBeNull()
    })

    test('viewing an item records the step it was viewed from, and closing it clears the step', () => {
        logic.actions.viewItem('flag-created')
        expect(logic.values.viewedStepKey).toBe('flag-created')

        logic.actions.closeItem()
        expect(logic.values.viewedStepKey).toBeNull()
    })

    test('each thread key keeps its own state', () => {
        const other = workThreadLogic({ threadKey: finishedWorkThread.key })
        other.mount()
        logic.actions.setStepExpanded('release-planned', true)

        expect(other.values.expandedOverrides).toEqual({})
        other.unmount()
    })
})
