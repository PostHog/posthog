import { urls } from 'scenes/urls'

import { WarehouseConsoleReady } from '../WarehouseConsole/WarehouseConsoleReady'
import { WarehouseGettingStartedStep } from './WarehouseGettingStartedStep'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

/** The steps for the managed warehouse itself. They mount only with the console flag on and the warehouse ready. */
export function WarehouseConsoleSteps(): JSX.Element {
    return (
        <WarehouseConsoleReady>
            <WarehouseGettingStartedStep
                step="connect_tool"
                index={3}
                state="todo"
                title="Connect a tool"
                description="Query your warehouse from a SQL client, a notebook or a BI tool."
                actions={[
                    {
                        label: 'See how to connect',
                        to: urls.warehouseConnect(),
                        dataAttr: 'warehouse-home-connect-tool',
                    },
                ]}
            />
            <WarehouseGettingStartedStep
                step="create_login"
                index={4}
                state="todo"
                title="Create a project login"
                description="Give a tool its own login so you can tell its queries apart."
                actions={[
                    { label: 'Open access', to: urls.warehouseAccess(), dataAttr: 'warehouse-home-create-login' },
                ]}
            />
        </WarehouseConsoleReady>
    )
}
