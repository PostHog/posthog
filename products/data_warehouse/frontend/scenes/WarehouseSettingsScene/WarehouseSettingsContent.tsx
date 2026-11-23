import { useActions, useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehousePasswordRevealDialog } from '../WarehouseConsole/WarehousePasswordRevealDialog'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseDeprovisionSection } from './WarehouseDeprovisionSection'
import { WarehouseDirectCredentials } from './WarehouseDirectCredentials'
import { WarehouseOnboardSection } from './WarehouseOnboardSection'
import { WarehouseProvisionSection } from './WarehouseProvisionSection'
import { WarehouseSettingsStatus } from './WarehouseSettingsStatus'
import { warehouseSettingsState } from './warehouseSettingsView'

const ADMIN_NOTE = 'Ask an organization admin to set up or change the warehouse.'

/** Picks what the Settings page shows. This page runs where the warehouse is set up, so it has no "ready" gate. */
export function WarehouseSettingsContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)
    const { loadWarehouseStatus } = useActions(warehouseConsoleLogic)
    const { warehouseStatus, warehouseStatusResolved, needsTeamOnboarding, initialPassword, orgDeletionFailed } =
        useValues(warehouseProvisioningLogic)
    const { clearInitialPassword } = useActions(warehouseProvisioningLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const isAdmin = !adminRestrictionReason
    const { view } = warehouseSettingsState(warehouseStatus, warehouseStatusResolved)

    if (consoleState === 'error') {
        return (
            <WarehouseResourceError
                title="Couldn't load your warehouse"
                onRetry={loadWarehouseStatus}
                data-attr="warehouse-settings-retry"
            />
        )
    }
    if (view === 'loading') {
        return <Skeleton className="h-32 w-full" />
    }

    return (
        <>
            <WarehousePasswordRevealDialog
                reveal={
                    initialPassword
                        ? {
                              username: warehouseStatus?.trino?.connection?.username ?? 'root',
                              password: initialPassword,
                              reason: 'reset',
                          }
                        : null
                }
                onClose={clearInitialPassword}
            />
            {orgDeletionFailed && (
                <Text size="sm" variant="muted">
                    Couldn't remove the old warehouse record. Refresh the page to try again.
                </Text>
            )}
            <WarehouseSettingsStatus />
            {view === 'none' || view === 'failed' ? (
                isAdmin ? (
                    <WarehouseProvisionSection failed={view === 'failed'} />
                ) : (
                    <Text variant="muted">{ADMIN_NOTE}</Text>
                )
            ) : null}
            {view === 'ready' && needsTeamOnboarding ? (
                isAdmin ? (
                    <WarehouseOnboardSection />
                ) : (
                    <Text variant="muted">
                        This project is not part of the warehouse yet. Ask an organization admin to enable it.
                    </Text>
                )
            ) : null}
            {view === 'ready' && <WarehouseDirectCredentials />}
            {view === 'ready' && isAdmin && <WarehouseDeprovisionSection />}
        </>
    )
}
