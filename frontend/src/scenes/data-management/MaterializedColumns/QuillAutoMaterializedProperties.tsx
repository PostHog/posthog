import { useValues } from 'kea'

import { Badge, Heading, Spinner, Text } from '@posthog/quill'

import { AutoMaterializedColumn, materializedColumnsLogic } from './materializedColumnsLogic'

/** The properties PostHog already materializes, on the quill materialized columns page. */
export function QuillAutoMaterializedProperties(): JSX.Element {
    const { autoMaterializedColumns, autoMaterializedColumnsLoading } = useValues(materializedColumnsLogic)

    return (
        <div className="flex flex-col gap-2">
            <Heading size="base" render={<h3 className="m-0" />}>
                Auto-materialized properties
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                These properties are already automatically materialized by PostHog. You're already getting all the
                performance gains we can provide!
            </Text>
            {autoMaterializedColumnsLoading ? (
                <div className="flex items-center justify-center py-8">
                    <Spinner />
                </div>
            ) : autoMaterializedColumns.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No auto-materialized properties found.
                </Text>
            ) : (
                <div className="flex flex-wrap gap-2">
                    {autoMaterializedColumns.map((column: AutoMaterializedColumn) => (
                        <Badge key={column.column_name}>{column.property_name}</Badge>
                    ))}
                </div>
            )}
        </div>
    )
}
