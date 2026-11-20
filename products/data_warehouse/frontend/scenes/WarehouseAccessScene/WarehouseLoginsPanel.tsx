import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { WarehouseDeleteLoginDialog } from './WarehouseDeleteLoginDialog'
import { WarehouseLoginsBody } from './WarehouseLoginsBody'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'
import { WarehouseNewLoginDialog } from './WarehouseNewLoginDialog'
import { WarehouseRevealedPasswordDialog } from './WarehouseRevealedPasswordDialog'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** The logins card. Mounted only for organization admins. */
export function WarehouseLoginsPanel(): JSX.Element {
    const { isCreating } = useValues(warehouseLoginsLogic)
    const { openNewLogin } = useActions(warehouseLoginsLogic)
    return (
        <Card>
            <CardHeader>
                <CardTitle>Logins</CardTitle>
                <CardDescription>
                    A project login can query that project's tables through Trino. Anyone with its password can use it.
                </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <div>
                    <Button
                        variant="primary"
                        loading={isCreating}
                        onClick={() => {
                            posthog.capture('warehouse access new login clicked')
                            openNewLogin()
                        }}
                        data-attr="warehouse-access-new-login"
                    >
                        New login
                    </Button>
                </div>
                <WarehouseLoginsBody />
            </CardContent>
            <WarehouseNewLoginDialog />
            <WarehouseDeleteLoginDialog />
            <WarehouseRevealedPasswordDialog />
        </Card>
    )
}
