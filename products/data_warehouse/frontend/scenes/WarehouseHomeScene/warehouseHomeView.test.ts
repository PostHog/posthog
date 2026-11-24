import type { WarehouseConsoleState } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseHomeView, warehouseHomeView } from './warehouseHomeView'

describe('warehouseHomeView', () => {
    it.each<[WarehouseConsoleState, WarehouseHomeView]>([
        ['loading', 'loading'],
        ['no_warehouse', 'explainer'],
        ['error', 'overview'],
        ['not_ready', 'overview'],
        ['ready', 'overview'],
    ])('with state %s shows %s', (consoleState, expected) => {
        expect(warehouseHomeView(consoleState)).toBe(expected)
    })
})
