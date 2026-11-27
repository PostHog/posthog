import { useValues } from 'kea'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { AutoMaterializedColumn, materializedColumnsLogic } from './materializedColumnsLogic'

/** The properties PostHog already materializes, on the materialized columns page. */
export function AutoMaterializedProperties(): JSX.Element {
    const { autoMaterializedColumns, autoMaterializedColumnsLoading } = useValues(materializedColumnsLogic)

    return (
        <div>
            <h3 className="text-lg font-semibold mb-2">Auto-materialized properties</h3>
            <p className="text-sm text-muted mb-4">
                These properties are already automatically materialized by PostHog. You're already getting all the
                performance gains we can provide!
            </p>
            {autoMaterializedColumnsLoading ? (
                <div className="flex items-center justify-center py-8">
                    <Spinner />
                </div>
            ) : autoMaterializedColumns.length === 0 ? (
                <div className="text-muted text-sm">No auto-materialized properties found.</div>
            ) : (
                <div className="flex flex-wrap gap-2">
                    {autoMaterializedColumns.map((column: AutoMaterializedColumn) => (
                        <LemonTag key={column.column_name} type="default">
                            {column.property_name}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}
