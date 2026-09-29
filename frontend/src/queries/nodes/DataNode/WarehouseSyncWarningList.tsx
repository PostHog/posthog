import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DataWarehouseSyncWarning } from '~/queries/schema/schema-general'

import { trimRedundantTail } from './warehouseSyncWarnings'

export function WarehouseSyncWarningList({ warnings }: { warnings: DataWarehouseSyncWarning[] }): JSX.Element {
    return (
        <ul className="list-disc pl-5">
            {warnings.map((warning, index) => (
                <li key={`${warning.table_name}-${warning.schema_name}-${index}`}>
                    <span>{trimRedundantTail(warning.message)}</span>
                    {warning.source_id && (
                        <>
                            {' '}
                            <Link to={urls.dataWarehouseSource(`managed-${warning.source_id}`)} target="_blank">
                                Manage source
                            </Link>
                        </>
                    )}
                </li>
            ))}
        </ul>
    )
}
