import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Button } from '@posthog/quill'

import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseNameField } from './WarehouseNameField'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** Adds this project to the organization's running warehouse. Mounted for organization admins. */
export function WarehouseOnboardSection(): JSX.Element {
    const { schemaName, isValidSchemaName, schemaNameAvailable, schemaNameChecking, isOnboardingTeam, canOnboardTeam } =
        useValues(warehouseProvisioningLogic)
    const { setSchemaName, onboardTeam } = useActions(warehouseProvisioningLogic)

    return (
        <WarehouseSection
            title="Enable this project"
            description="The organization's warehouse is running, but this project is not part of it yet."
        >
            <div className="flex max-w-xl flex-col gap-4">
                <WarehouseNameField
                    id="warehouse-onboard-schema-name"
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
                    help="This project's data lands in its own schema so it doesn't mix with other projects. You can't change it later."
                />
                <div>
                    <Button
                        variant="primary"
                        loading={isOnboardingTeam}
                        disabledReason={canOnboardTeam ? undefined : 'Enter an available schema name'}
                        onClick={() => {
                            posthog.capture('warehouse settings action clicked', { action: 'onboard_project' })
                            onboardTeam({ schemaName })
                        }}
                        data-attr="onboard-warehouse-team"
                    >
                        Enable this project
                    </Button>
                </div>
            </div>
        </WarehouseSection>
    )
}
