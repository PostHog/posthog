import { columnConfiguratorLogic } from 'lib/components/ResizableTable/columnConfiguratorLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'

describe('the column configurator lets the user change which columns should be visible', () => {
    let logic: ReturnType<typeof columnConfiguratorLogic.build>

    const selectedColumns = ['a', 'b', 'ant', 'aardvark']

    beforeEach(() => {
        initKeaTests()
        logic = columnConfiguratorLogic({ selectedColumns })
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
})
