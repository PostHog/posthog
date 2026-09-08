import { initKeaTests } from '~/test/init'

import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { ticketFilterBarLogic } from './ticketFilterBarLogic'

describe('ticketFilterBarLogic', () => {
    let sceneLogic: ReturnType<typeof supportTicketsSceneLogic.build>
    let logic: ReturnType<typeof ticketFilterBarLogic.build>

    beforeEach(() => {
        initKeaTests()
        sceneLogic = supportTicketsSceneLogic()
        sceneLogic.mount()
        logic = ticketFilterBarLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        sceneLogic.unmount()
    })

    it('always shows the date range and never offers it in the add menu', () => {
        expect(logic.values.visibleFilterKeys).toEqual(['date'])
        expect(logic.values.addableFilterKeys).not.toContain('date')
    })

    it('shows a filter from the moment it is added until its value is cleared', () => {
        logic.actions.openFilter('status')
        expect(logic.values.visibleFilterKeys).toEqual(['status', 'date'])
        expect(logic.values.addableFilterKeys).not.toContain('status')

        // A value keeps the chip visible even after the "open" state is dropped.
        sceneLogic.actions.setStatusFilter(['open'])
        logic.actions.closeFilter('status')
        expect(logic.values.visibleFilterKeys).toEqual(['status', 'date'])

        sceneLogic.actions.setStatusFilter([])
        expect(logic.values.visibleFilterKeys).toEqual(['date'])
    })

    it('drops filters that were added but never set when the filters are reset', () => {
        logic.actions.openFilter('priority')
        logic.actions.openFilter('channel')
        sceneLogic.actions.setChannelFilter('email')

        sceneLogic.actions.resetFilters()

        expect(logic.values.openFilterKeys).toEqual([])
        expect(logic.values.visibleFilterKeys).toEqual(['date'])
    })

    it('offers the AI result filter only when AI suggestions are enabled', () => {
        expect(logic.values.aiEnabled).toBe(false)
        expect(logic.values.addableFilterKeys).not.toContain('aiTriageResult')
    })
})
