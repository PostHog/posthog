import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { warehouseStorageLogic } from './warehouseStorageLogic'

export function WarehouseStorageMaintenance(): JSX.Element {
    const { storage, maintenanceFields } = useValues(warehouseStorageLogic)

    return (
        <WarehouseSection title="Maintenance" data-attr="warehouse-storage-maintenance">
            {storage?.maintenance && maintenanceFields.length > 0 ? (
                <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 @lg/warehouse-storage:grid-cols-2">
                    {maintenanceFields.map((field) => (
                        <div key={field.label} className="flex min-w-0 flex-col">
                            <Text size="xs" variant="muted" render={<dt />}>
                                {field.label}
                            </Text>
                            <Text size="sm" className="break-words" render={<dd className="m-0" />}>
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
        </WarehouseSection>
    )
}
