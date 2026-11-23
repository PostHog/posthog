import posthog from 'posthog-js'

import { Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import type { WarehouseTrinoConnectionApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { WarehouseCopyButton } from './WarehouseCopyButton'

// pinned: the analytics event name in this file feeds dashboards, so renaming it breaks them.

function Field({ label, value, target }: { label: string; value: string; target: string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center justify-between gap-2 rounded-md border px-3 py-1.5">
            <div className="min-w-0">
                <Text size="xs" variant="muted" render={<div />}>
                    {label}
                </Text>
                <Text size="sm" className="block truncate font-mono" title={value} render={<code />}>
                    {value}
                </Text>
            </div>
            <WarehouseCopyButton iconOnly value={value} thing={label.toLowerCase()} target={target} />
        </div>
    )
}

export function WarehouseConnectDetails({
    connection,
    schemaName,
}: {
    connection: WarehouseTrinoConnectionApi
    schemaName: string | null
}): JSX.Element {
    return (
        <WarehouseSection
            title="Connection details"
            description="Sign in with a warehouse login."
            controls={
                <WarehouseSectionLink
                    to={urls.warehouseAccess()}
                    onClick={() => posthog.capture('warehouse connect access clicked')}
                    data-attr="warehouse-connect-open-access"
                >
                    Manage logins
                </WarehouseSectionLink>
            }
        >
            <div className="@container/connect-details">
                <div className="grid grid-cols-1 gap-2 @lg/connect-details:grid-cols-2">
                    <Field label="Host" value={connection.host} target="host" />
                    <Field label="Port" value={String(connection.port)} target="port" />
                    <Field label="Catalog" value={connection.catalog} target="catalog" />
                    {schemaName && <Field label="Schema" value={schemaName} target="schema" />}
                </div>
            </div>
        </WarehouseSection>
    )
}
