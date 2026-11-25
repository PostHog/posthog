import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Button } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseDeleteLoginDialog } from './WarehouseDeleteLoginDialog'
import { WarehouseLoginsBody } from './WarehouseLoginsBody'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'
import { WarehouseNewLoginDialog } from './WarehouseNewLoginDialog'
import { WarehouseResetPasswordDialog } from './WarehouseResetPasswordDialog'
import { WarehouseRevealedPasswordDialog } from './WarehouseRevealedPasswordDialog'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** The logins section. Mounted only for organization admins. */
export function WarehouseLoginsPanel(): JSX.Element {
    const { isCreating } = useValues(warehouseLoginsLogic)
    const { openNewLogin } = useActions(warehouseLoginsLogic)

    return (
        <>
            <WarehouseSection
                flush
                title="Logins"
                description="Anyone with a login's password can use it. A project login can query that project's tables."
                controls={
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
                }
            >
                <WarehouseLoginsBody />
            </WarehouseSection>
            <WarehouseNewLoginDialog />
            <WarehouseDeleteLoginDialog />
            <WarehouseResetPasswordDialog />
            <WarehouseRevealedPasswordDialog />
        </>
    )
}
