import { columnConfiguratorLogic } from 'lib/components/ResizableTable/columnConfiguratorLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { teamLogic } from 'scenes/teamLogic'

describe('the column configurator lets the user change which columns should be visible', () => {
    let logic: ReturnType<typeof columnConfiguratorLogic.build>

    const selectedColumns = ['a', 'b', 'ant', 'aardvark']

    beforeEach(() => {
        initKeaTests()
        logic = columnConfiguratorLogic({ selectedColumns, onSaveAsDefault: () => {} })
        logic.mount()
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            selectedColumns: selectedColumns,
        })
    })

    it('sets selected columns on save', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectColumn('d')
            logic.actions.save()
        }).toDispatchActions([tableConfigLogic.actionCreators.setSelectedColumns(['a', 'b', 'ant', 'aardvark', 'd'])])
    })

    it('sets selected columns to those provided on reset', async () => {
        const defaultColumns = ['1', '2']
        await expectLogic(logic, () => {
            logic.actions.resetColumns(defaultColumns)
        }).toMatchValues({
            selectedColumns: defaultColumns,
        })
    })

    it('cannot duplicate columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectColumn('added')
            logic.actions.selectColumn('added')
        }).toMatchValues({
            selectedColumns: ['a', 'b', 'ant', 'aardvark', 'added'],
        })
    })

    it('sets toggle to save columns as default', async () => {
        await expectLogic(logic, () => {
            logic.actions.toggleSaveAsDefault()
        }).toMatchValues({
            saveAsDefault: true,
        })
    })

    it.only('saves columns as default', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectColumn('added')
            logic.actions.toggleSaveAsDefault()
        }).toDispatchActions([
            teamLogic.actionCreators.updateCurrentTeam({ live_events_columns: ['a', 'b', 'ant', 'aardvark', 'added'] }),
        ])
    })
})
