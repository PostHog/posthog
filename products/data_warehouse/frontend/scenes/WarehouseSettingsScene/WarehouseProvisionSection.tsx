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
    Text,
} from '@posthog/quill'

import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseNameField } from './WarehouseNameField'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** The form that creates the organization's warehouse, or retries a failed attempt. Mounted for organization admins. */
export function WarehouseProvisionSection({ failed }: { failed: boolean }): JSX.Element {
    const {
        databaseName,
        databaseNameAvailable,
        databaseNameChecking,
        isValidDatabaseName,
        schemaName,
        schemaNameAvailable,
        schemaNameChecking,
        isValidSchemaName,
        isProvisioning,
        canProvision,
        canRetryProvision,
        retryDatabaseName,
    } = useValues(warehouseProvisioningLogic)
    const { setDatabaseName, setSchemaName, provisionWarehouse } = useActions(warehouseProvisioningLogic)
    const ready = failed ? canRetryProvision : canProvision
    const action = failed ? 'retry_provision' : 'provision'

    return (
        <WarehouseSection
            title={failed ? 'Retry setup' : 'Set up your warehouse'}
            description="One managed warehouse is shared by every project in your organization. Setup takes a few minutes."
        >
            <div className="flex max-w-xl flex-col gap-4">
                <WarehouseNameField
                    id="warehouse-name"
                    label="Warehouse name"
                    value={databaseName}
                    onChange={setDatabaseName}
                    placeholder="my-warehouse"
                    valid={isValidDatabaseName}
                    available={databaseNameAvailable}
                    checking={databaseNameChecking}
                    formatError="Use 3 to 63 characters: lowercase letters, numbers and hyphens, starting with a letter and ending with a letter or number."
                    unavailableError="This warehouse name is already taken."
                    unknownError={
                        failed
                            ? 'Availability checks are advisory when you retry.'
                            : "Couldn't check whether this name is available."
                    }
                    help="The name is part of your connection host and catalog."
                />
                <WarehouseNameField
                    id="warehouse-schema-name"
                    label="Schema name"
                    value={schemaName}
                    onChange={setSchemaName}
                    placeholder="my_project"
                    valid={isValidSchemaName}
                    available={schemaNameAvailable}
                    checking={schemaNameChecking}
                    formatError="Use lowercase letters, numbers and underscores only, up to 63 characters."
                    unavailableError="Another project in your organization already uses this schema name."
                    unknownError="Couldn't check whether this schema name is available."
                    help="This project's data lands in its own schema. Other projects pick theirs when they join. You can't change it later."
                />
                <div>
                    <AlertDialog>
                        <AlertDialogTrigger
                            render={
                                <Button
                                    variant="primary"
                                    loading={isProvisioning}
                                    disabledReason={
                                        ready ? undefined : 'Enter an available warehouse name and schema name'
                                    }
                                    onClick={() => posthog.capture('warehouse settings action clicked', { action })}
                                    data-attr={failed ? 'retry-provision-warehouse' : 'provision-warehouse'}
                                />
                            }
                        >
                            {failed ? 'Retry setup' : 'Set up warehouse'}
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                            <AlertDialogHeader>
                                <AlertDialogTitle>
                                    {failed ? 'Retry setting up the warehouse?' : 'Set up the managed warehouse?'}
                                </AlertDialogTitle>
                                <AlertDialogDescription>
                                    This creates a managed warehouse for your organization, shared by every project in
                                    it. It takes less than 5 minutes.
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                                <AlertDialogClose
                                    render={<Button variant="primary" />}
                                    onClick={() => provisionWarehouse({ databaseName: retryDatabaseName, schemaName })}
                                >
                                    {failed ? 'Retry setup' : 'Set up'}
                                </AlertDialogClose>
                            </AlertDialogFooter>
                        </AlertDialogContent>
                    </AlertDialog>
                </div>
                <Text size="xs" variant="muted">
                    The password for the root login is shown once when setup finishes.
                </Text>
            </div>
        </WarehouseSection>
    )
}
