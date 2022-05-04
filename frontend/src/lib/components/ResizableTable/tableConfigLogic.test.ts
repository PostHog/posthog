import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'

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

    describe('column choices are stored in the URL', () => {
        it('reads from the URL when present', async () => {
            router.actions.push(router.values.location.pathname, { tableColumns: ['egg', 'beans', 'toast'] })
            await expectLogic(logic).toMatchValues({
                selectedColumns: ['egg', 'beans', 'toast'],
            })
        })

        it('writes to the URL when column config changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSelectedColumns(['soup', 'bread', 'greens'])
            })
            expect(router.values.searchParams).toHaveProperty('tableColumns', ['soup', 'bread', 'greens'])
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

    it('sets table width to one more than column length to account for the button column', async () => {
        await expectLogic(logic, () => logic.actions.setSelectedColumns(['a', 'b'])).toMatchValues({
            tableWidth: 3,
        })
    })
})
