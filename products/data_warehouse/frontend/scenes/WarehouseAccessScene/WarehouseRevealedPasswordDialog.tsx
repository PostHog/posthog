import { useActions, useValues } from 'kea'

import { WarehousePasswordRevealDialog } from '../WarehouseConsole/WarehousePasswordRevealDialog'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'

export function WarehouseRevealedPasswordDialog(): JSX.Element {
    const { activeReveal } = useValues(warehouseLoginsLogic)
    const { closeReveal } = useActions(warehouseLoginsLogic)

    return <WarehousePasswordRevealDialog reveal={activeReveal} onClose={closeReveal} />
}
