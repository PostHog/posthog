import { columnConfiguratorLogic } from 'lib/components/ResizableTable/columnConfiguratorLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'

describe('the column configurator lets the user change which columns should be visible', () => {
    let logic: ReturnType<typeof columnConfiguratorLogic.build>

    const selectedColumns = ['a', 'b', 'ant', 'aardvark']
    const availableColumns = [...selectedColumns, 'c', 'd', 'e']

    initKeaTestLogic({
        logic: columnConfiguratorLogic,
        props: { availableColumns, selectedColumns },
        onLogic: (l) => {
            logic = l
        },
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            columnFilter: '',
            visibleColumns: selectedColumns,
            filteredVisibleColumns: selectedColumns,
            hiddenColumns: ['c', 'd', 'e'],
            filteredHiddenColumns: ['c', 'd', 'e'],
            scrollIndex: 4,
        })
    })

    it('selecting a column moves it from hidden to visible and updates the scroll index', () => {
        expectLogic(logic, () => logic.actions.selectColumn('d')).toMatchValues({
            hiddenColumns: ['c', 'e'],
            visibleColumns: ['a', 'b', 'ant', 'aardvark', 'd'],
            scrollIndex: 5,
        })
    })

    it('unselecting a column moves it from visible to hidden and updates the scroll index', () => {
        expectLogic(logic, () => logic.actions.unselectColumn('a')).toMatchValues({
            hiddenColumns: ['c', 'd', 'e', 'a'],
            visibleColumns: ['b', 'ant', 'aardvark'],
            scrollIndex: 3,
        })
    })

    it('can set the column filter', () => {
        expectLogic(logic, () => logic.actions.setColumnFilter('123')).toMatchValues({ columnFilter: '123' })
    })

    it('setting the column filter, fitlers the visible and hidden columns', () => {
        expectLogic(logic, () => logic.actions.setColumnFilter('a')).toMatchValues({
            columnFilter: 'a',
            filteredHiddenColumns: [],
            filteredVisibleColumns: ['a', 'ant', 'aardvark'],
        })
    })

    it('sets selected columns to visible columns on save', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectColumn('d')
            logic.actions.save()
        }).toDispatchActions([tableConfigLogic.actionCreators.setSelectedColumns(['a', 'b', 'ant', 'aardvark', 'd'])])
    })

    it('sets selected columns to provided on reset', async () => {
        await expectLogic(logic, () => {
            logic.actions.resetColumns(['1', '2'])
        }).toDispatchActions([tableConfigLogic.actionCreators.setSelectedColumns(['1', '2'])])
    })
})
