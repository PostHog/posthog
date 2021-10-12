import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { router } from 'kea-router'
import { mockAPI } from 'lib/api.mock'

jest.mock('lib/api')

describe('tableConfigLogic', () => {
    let logic: ReturnType<typeof tableConfigLogic.build>

    mockAPI(async ({ pathname, searchParams, method }) => {
        throw new Error(`Unmocked ${method} fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
    })

    initKeaTestLogic({
        logic: tableConfigLogic,
        props: {},
        onLogic: (l) => {
            logic = l
        },
    })

    it('starts with expected defaults', async () => {
        await expectLogic(logic).toMatchValues({
            modalVisible: false,
            selectedColumns: 'DEFAULT',
            usersUnsavedSelection: [],
            defaultColumns: [],
            allPossibleColumns: [],
            tableWidth: 7,
        })
    })

    it('can set the default columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDefaultColumns(['a', 'b'])
        }).toMatchValues({
            defaultColumns: ['a', 'b'],
        })
    })

    it('can set the selection currently being edited', async () => {
        await expectLogic(logic, () => {
            logic.actions.setUsersUnsavedSelection(['c', 'd'])
        }).toMatchValues({
            usersUnsavedSelection: ['c', 'd'],
        })
    })

    it('uses default columns for the selection currently being edited if there is not already a selection', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDefaultColumns(['a', 'b'])
        }).toMatchValues({
            usersUnsavedSelection: ['a', 'b'],
        })
    })

    it('does not uses default columns for the selection currently being edited if there is already a selection', async () => {
        await expectLogic(logic, () => {
            logic.actions.setUsersUnsavedSelection(['c', 'd'])
            logic.actions.setDefaultColumns(['a', 'b'])
        }).toMatchValues({
            usersUnsavedSelection: ['c', 'd'],
        })
    })

    it('replaces the default columns when user is editing', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDefaultColumns(['a', 'b'])
            logic.actions.setUsersUnsavedSelection(['c', 'e'])
        }).toMatchValues({
            usersUnsavedSelection: ['c', 'e'],
        })
    })

    it('can set all possible columns', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAllPossibleColumns(['a', 'b'])
        }).toMatchValues({
            allPossibleColumns: ['a', 'b'],
        })
    })

    describe('selectable columns are any that are possible but not currently selected', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAllPossibleColumns(['a', 'b', 'c', 'd'])
            logic.actions.setDefaultColumns(['a', 'b'])
        }).toMatchValues({
            selectableColumns: ['c', 'd'],
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
