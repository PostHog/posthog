import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { columnConfiguratorLogic } from './columnConfiguratorLogic'

describe('columnConfiguratorLogic', () => {
    let logic: ReturnType<typeof columnConfiguratorLogic.build>

    const startingColumns = ['a', 'b', 'ant', 'aardvark']

    beforeEach(() => {
        initKeaTests()
        logic = columnConfiguratorLogic({ key: 'uniqueKey', columns: startingColumns, setColumns: () => {} })
        logic.mount()
    })

    it('starts with expected defaults', async () => {
        await expectLogic(logic).toMatchValues({
            modalVisible: false,
            columns: startingColumns,
        })
    })

    it('can show modal', async () => {
        await expectLogic(logic, () => logic.actions.showModal()).toMatchValues({
            modalVisible: true,
        })
    })

    it('can hide the modal', async () => {
        await expectLogic(logic, () => logic.actions.hideModal()).toMatchValues({
            modalVisible: false,
        })
    })

    it('sets modal to hidden when user has selected and saved columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.showModal()
            logic.actions.setColumns(['a'])
            logic.actions.save()
        }).toMatchValues({
            modalVisible: false,
        })
    })

    it('cannot duplicate columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectColumn('added')
            logic.actions.selectColumn('added')
        }).toMatchValues({
            columns: ['a', 'b', 'ant', 'aardvark', 'added'],
        })
    })

    // Regression guard for the events Activity page dead-end: a non-events table that lacks its own
    // contextKey must not fall back to writing the events-scoped `live_events_columns`.
    it('does not persist live_events_columns when a non-events table saves as default', async () => {
        teamLogic.mount()
        const updateSpy = jest.spyOn(teamLogic.actions, 'updateCurrentTeam')
        const nonEventsLogic = columnConfiguratorLogic({
            key: 'non-events',
            columns: ['session_id'],
            setColumns: () => {},
            isPersistent: true,
            context: undefined,
        })
        nonEventsLogic.mount()

        await expectLogic(nonEventsLogic, () => {
            nonEventsLogic.actions.toggleSaveAsDefault()
            nonEventsLogic.actions.save()
        }).toFinishAllListeners()

        expect(updateSpy).not.toHaveBeenCalled()
    })

    it('persists live_events_columns when the events table saves as default', async () => {
        teamLogic.mount()
        const updateSpy = jest.spyOn(teamLogic.actions, 'updateCurrentTeam')
        const eventsLogic = columnConfiguratorLogic({
            key: 'events',
            columns: ['event', 'timestamp'],
            setColumns: () => {},
            isPersistent: true,
            context: { type: 'team_columns' },
        })
        eventsLogic.mount()

        await expectLogic(eventsLogic, () => {
            eventsLogic.actions.toggleSaveAsDefault()
            eventsLogic.actions.save()
        }).toFinishAllListeners()

        expect(updateSpy).toHaveBeenCalledWith(
            expect.objectContaining({ live_events_columns: expect.arrayContaining(['event', 'timestamp']) })
        )
    })
})
