import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from 'products/data_warehouse/frontend/generated/api'

import { consoleErrorMessage } from '../WarehouseConsole/consoleErrorMessage'
import { warehouseLoginActions } from './warehouseLoginActions'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    managedWarehouseConsoleLoginsRetrieve: jest.fn().mockResolvedValue({ logins: [] }),
    managedWarehouseConsoleLoginsCreate: jest.fn(),
    managedWarehouseConsoleLoginsDestroy: jest.fn(),
    managedWarehouseConsoleLoginsPartialUpdate: jest.fn(),
    managedWarehouseConsoleLoginsRotateCreate: jest.fn(),
}))

describe('warehouse logins', () => {
    it.each([
        ['root', { canRotate: false, canDisable: false, canDelete: false, canReset: true }],
        ['other', { canRotate: false, canDisable: false, canDelete: false, canReset: false }],
        ['project_reader', { canRotate: true, canDisable: true, canDelete: true, canReset: false }],
        ['project_user', { canRotate: true, canDisable: true, canDelete: true, canReset: false }],
    ] as const)('offers the right actions for a %s login', (kind, expected) => {
        expect(warehouseLoginActions(kind)).toEqual(expected)
    })

    it.each([
        [{ data: { error: 'Server said no' }, message: 'x' }, 'Server said no'],
        [{ data: { detail: 'Detail text' } }, 'Detail text'],
        [new Error('Network down'), 'Network down'],
        [{}, 'Fallback'],
    ])('picks the error message from %j', (error, expected) => {
        expect(consoleErrorMessage(error, 'Fallback')).toBe(expected)
    })

    it('a failed create resets isCreating and reveals nothing', async () => {
        initKeaTests()
        jest.mocked(api.managedWarehouseConsoleLoginsCreate).mockRejectedValue({ data: { error: 'No' } })
        const logic = warehouseLoginsLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.createLogin())
            .toDispatchActions(['createLogin', 'createLoginDone'])
            .toMatchValues({ isCreating: false, revealedPassword: null })
    })

    it('keeps a revealed password only until the reveal is closed', async () => {
        initKeaTests()
        const logic = warehouseLoginsLogic()
        logic.mount()

        await expectLogic(logic, () =>
            logic.actions.revealPassword({ username: 'u', password: 'secret', reason: 'created' })
        ).toMatchValues({ revealedPassword: { username: 'u', password: 'secret', reason: 'created' } })
        await expectLogic(logic, () => logic.actions.closeReveal()).toMatchValues({ revealedPassword: null })
    })
})
