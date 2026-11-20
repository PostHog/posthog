import { Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import type { WarehouseTrinoConnectionApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { WarehouseCopyButton } from './WarehouseCopyButton'

function Field({ label, value, target }: { label: string; value: string; target: string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center justify-between gap-2 rounded-md border px-3 py-2">
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
        <Card>
            <CardHeader>
                <CardTitle>Connection details</CardTitle>
            </CardHeader>
            <CardContent className="@container/connect-details">
                <div className="grid grid-cols-1 gap-2 @lg/connect-details:grid-cols-2">
                    <Field label="Host" value={connection.host} target="host" />
                    <Field label="Port" value={String(connection.port)} target="port" />
                    <Field label="Catalog" value={connection.catalog} target="catalog" />
                    {schemaName && <Field label="Schema" value={schemaName} target="schema" />}
                    <Field label="Username" value={connection.username} target="username" />
                </div>
            </CardContent>
        </Card>
    )
}
