import { useValues } from 'kea'

import { Badge, Text } from '@posthog/quill'

import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { formatAbsoluteTime } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WAREHOUSE_STATE_LABELS, warehouseSettingsState } from './warehouseSettingsView'

function badgeVariant(state: string | null): 'success' | 'warning' | 'destructive' | 'default' {
    switch (state) {
        case 'ready':
            return 'success'
        case 'pending':
        case 'provisioning':
        case 'deleting':
        case 'not_enabled':
        case 'unavailable':
            return 'warning'
        case 'failed':
            return 'destructive'
        default:
            return 'default'
    }
}

export function WarehouseSettingsStatus(): JSX.Element | null {
    const { warehouseStatus, warehouseStatusResolved, teamOnboarded, teamSchemaName, deprovisionTakingLong } =
        useValues(warehouseProvisioningLogic)
    const { state, message, readyAt } = warehouseSettingsState(warehouseStatus, warehouseStatusResolved)

    if (!state) {
        return null
    }
    return (
        <WarehouseSection
            title="Status"
            description="This warehouse is shared by every project in the organization."
            controls={<Badge variant={badgeVariant(state)}>{WAREHOUSE_STATE_LABELS[state] ?? state}</Badge>}
        >
            <div className="flex flex-col gap-1">
                {message && (
                    <Text size="sm" className={state === 'failed' ? 'text-destructive-foreground' : undefined}>
                        {message}
                    </Text>
                )}
                {deprovisionTakingLong && (
                    <Text size="xs" variant="muted">
                        Teardown is taking longer than usual. It keeps retrying until the warehouse is removed, so you
                        can leave this page.
                    </Text>
                )}
                {readyAt && (
                    <Text size="xs" variant="muted">
                        Ready since {formatAbsoluteTime(readyAt)}
                    </Text>
                )}
                {teamOnboarded && (
                    <Text size="xs" variant="muted">
                        This project's data lands in the{' '}
                        <code className="font-mono">{teamSchemaName ?? 'unknown'}</code> schema. The schema name cannot
                        be changed.
                    </Text>
                )}
            </div>
        </WarehouseSection>
    )
}
