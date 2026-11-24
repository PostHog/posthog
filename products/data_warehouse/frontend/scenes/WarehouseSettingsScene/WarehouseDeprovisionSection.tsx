import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
} from '@posthog/quill'

import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** Removes the organization's warehouse. Mounted for organization admins. */
export function WarehouseDeprovisionSection(): JSX.Element {
    const { isDeprovisioning } = useValues(warehouseProvisioningLogic)
    const { deprovisionWarehouse } = useActions(warehouseProvisioningLogic)

    return (
        <WarehouseSection
            title="Remove the warehouse"
            description="This deletes the warehouse and its data for every project in the organization."
        >
            <AlertDialog>
                <AlertDialogTrigger
                    render={
                        <Button
                            variant="destructive-outline"
                            loading={isDeprovisioning}
                            onClick={() =>
                                posthog.capture('warehouse settings action clicked', { action: 'deprovision' })
                            }
                            data-attr="deprovision-warehouse"
                        />
                    }
                >
                    Deprovision warehouse
                </AlertDialogTrigger>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Deprovision the managed warehouse?</AlertDialogTitle>
                        <AlertDialogDescription>
                            This deletes the managed warehouse for your organization and every project in it. This
                            cannot be undone.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                        <AlertDialogClose
                            render={<Button variant="destructive-outline" />}
                            onClick={() => deprovisionWarehouse()}
                        >
                            Deprovision
                        </AlertDialogClose>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </WarehouseSection>
    )
}
