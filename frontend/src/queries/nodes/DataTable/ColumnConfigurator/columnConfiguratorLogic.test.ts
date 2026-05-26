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

    it('treats transient load failures of saved column configuration as a benign degraded state', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/column_configurations/': () => [503, {}],
            },
        })

        const persistedLogic = columnConfiguratorLogic({
            key: 'persisted',
            columns: startingColumns,
            setColumns: () => {},
            contextKey: 'live_events',
        })
        persistedLogic.mount()

        await expectLogic(persistedLogic, () => {
            persistedLogic.actions.loadSavedColumnConfiguration()
        })
            .toDispatchActions(['loadSavedColumnConfigurationSuccess'])
            .toMatchValues({
                savedColumnConfiguration: null,
            })
    })
})
