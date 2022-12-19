import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

describe('tableConfigLogic', () => {
    let logic: ReturnType<typeof tableConfigLogic.build>

    const startingColumns = 'DEFAULT'

    beforeEach(() => {
        initKeaTests()
        logic = tableConfigLogic({ startingColumns })
        logic.mount()
    })

    it('starts with expected defaults', async () => {
        await expectLogic(logic).toMatchValues({
            modalVisible: false,
            selectedColumns: startingColumns,
            tableWidth: 7,
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

    it('sets modal to hidden when user has selected columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.showModal()
            logic.actions.setSelectedColumns(['a'])
        }).toMatchValues({
            modalVisible: false,
        })
    })

    it('sets table width to two more than column length to account for the Time and Actions column', async () => {
        await expectLogic(logic, () => logic.actions.setSelectedColumns(['a', 'b'])).toMatchValues({
            tableWidth: 4,
        })
    })
})
