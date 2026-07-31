import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
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

    describe('with a context key', () => {
        let setColumns: jest.Mock
        let posted: Record<string, any>[]
        let savedConfigurations: Record<string, any>[]

        beforeEach(() => {
            posted = []
            savedConfigurations = []
            useMocks({
                get: {
                    '/api/environments/:team_id/column_configurations/': () => [200, { results: savedConfigurations }],
                },
                post: {
                    '/api/environments/:team_id/column_configurations/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        posted.push(body)
                        return [201, { id: 'new-id', ...body }]
                    },
                },
            })
        })

        const mountContextKeyedLogic = (): void => {
            setColumns = jest.fn()
            logic.unmount()
            logic = columnConfiguratorLogic({
                key: 'contextKeyed',
                columns: startingColumns,
                setColumns,
                isPersistent: true,
                contextKey: 'activity-events',
            })
            logic.mount()
        }

        it('applies the persisted columns on mount', async () => {
            savedConfigurations = [{ id: 'saved-id', columns: ['timestamp', 'person'], visibility: 'private' }]
            mountContextKeyedLogic()

            await expectLogic(logic).toDispatchActions(['loadSavedColumnConfigurationsSuccess'])
            expect(setColumns).toHaveBeenCalledWith(['timestamp', 'person'])
        })

        it('prefers a personal configuration over the team-wide one', async () => {
            savedConfigurations = [
                { id: 'mine', columns: ['mine'], visibility: 'private' },
                { id: 'theirs', columns: ['theirs'], visibility: 'shared' },
            ]
            mountContextKeyedLogic()

            await expectLogic(logic).toDispatchActions(['loadSavedColumnConfigurationsSuccess'])
            expect(setColumns).toHaveBeenCalledWith(['mine'])
        })

        it('persists the selection privately on save without opting into the team default', async () => {
            mountContextKeyedLogic()
            await expectLogic(logic).toDispatchActions(['loadSavedColumnConfigurationsSuccess'])

            logic.actions.setColumns(['timestamp'])
            logic.actions.save()
            await expectLogic(logic).toFinishAllListeners()

            expect(posted).toEqual([{ context_key: 'activity-events', columns: ['timestamp'], visibility: 'private' }])
        })

        it('persists to the team-wide configuration when saving as default', async () => {
            mountContextKeyedLogic()
            await expectLogic(logic).toDispatchActions(['loadSavedColumnConfigurationsSuccess'])

            logic.actions.setColumns(['timestamp'])
            logic.actions.toggleSaveAsDefault()
            logic.actions.save()
            await expectLogic(logic).toFinishAllListeners()

            expect(posted).toEqual([{ context_key: 'activity-events', columns: ['timestamp'], visibility: 'shared' }])
        })
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
})
