import { expectLogic } from 'kea-test-utils'

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

    it('edits the column at the index the editor was opened on', async () => {
        await expectLogic(logic, () => logic.actions.openColumnEditor(2)).toMatchValues({
            editingColumnIndex: 2,
            editingColumn: 'ant',
        })

        await expectLogic(logic, () => logic.actions.saveEditedColumn('anteater')).toMatchValues({
            columns: ['a', 'b', 'anteater', 'aardvark'],
            editingColumnIndex: null,
            editingColumn: null,
        })
    })

    it.each([
        ['empty', ''],
        ['whitespace only', '   '],
        ['a newline', '\n'],
    ])('keeps the editor open when the edited expression is %s', async (_, expression) => {
        await expectLogic(logic, () => {
            logic.actions.openColumnEditor(2)
            logic.actions.saveEditedColumn(expression)
        }).toMatchValues({
            columns: startingColumns,
            editingColumnIndex: 2,
            editingColumn: 'ant',
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
