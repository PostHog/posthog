import { useValues } from 'kea'

import { Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import { warehouseStorageLogic } from './warehouseStorageLogic'

export function WarehouseStorageMaintenance(): JSX.Element {
    const { storage, maintenanceFields } = useValues(warehouseStorageLogic)

    return (
        <Card data-attr="warehouse-storage-maintenance">
            <CardHeader>
                <CardTitle>Maintenance</CardTitle>
            </CardHeader>
            <CardContent>
                {storage?.maintenance && maintenanceFields.length > 0 ? (
                    <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 @lg/warehouse-storage:grid-cols-2">
                        {maintenanceFields.map((field) => (
                            <div key={field.label} className="flex min-w-0 flex-col">
                                <Text size="xs" variant="muted" render={<dt />}>
                                    {field.label}
                                </Text>
                                <Text size="sm" className="break-words" render={<dd />}>
                                    {field.value}
                                </Text>
                            </div>
                        ))}
                    </dl>
                ) : (
                    <Text size="sm" variant="muted">
                        Not available
                    </Text>
                )}
            </CardContent>
        </Card>
    )
}
