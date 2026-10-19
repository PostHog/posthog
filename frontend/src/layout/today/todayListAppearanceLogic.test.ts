import { initKeaTests } from '~/test/init'

import { todayListAppearanceLogic } from './todayListAppearanceLogic'

describe('todayListAppearanceLogic', () => {
    let logic: ReturnType<typeof todayListAppearanceLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = todayListAppearanceLogic()
        logic.mount()
        logic.actions.setFields(['creator', 'space'])
        logic.actions.openAppearanceDialog()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens with the saved details checked and first, in their saved order', () => {
        expect(logic.values.draft).toEqual({
            order: ['creator', 'space', 'repository', 'branch', 'activity'],
            checked: ['creator', 'space'],
        })
    })

    it('saves the checked details in the order they were moved to', () => {
        logic.actions.toggleDraftField('activity', true)
        logic.actions.toggleDraftField('creator', false)
        logic.actions.moveDraftField('activity', -1)
        logic.actions.moveDraftField('space', 1)
        logic.actions.moveDraftField('activity', -1)
        logic.actions.saveAppearance()

        expect(logic.values.fields).toEqual(['activity', 'space'])
        expect(logic.values.dialogOpen).toBe(false)
    })

    it('drops an edit that was canceled, so the next opening starts from what is saved', () => {
        logic.actions.toggleDraftField('branch', true)
        logic.actions.moveDraftField('branch', -1)
        logic.actions.closeAppearanceDialog()
        logic.actions.openAppearanceDialog()

        expect(logic.values.fields).toEqual(['creator', 'space'])
        expect(logic.values.draftFields).toEqual(['creator', 'space'])
    })
})
