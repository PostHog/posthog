import { useActions, useValues } from 'kea'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { sourceSchemasModalLogic } from './sourceSchemasModalLogic'
import { sourceSchemaColumns } from './warehouseStatusDisplay'

export function SourceSchemasModal(): JSX.Element {
    const { activeSource, sourceSchemas, sourceSchemasLoading } = useValues(sourceSchemasModalLogic)
    const { closeSourceSchemasModal } = useActions(sourceSchemasModalLogic)

    return (
        <LemonModal
            isOpen={!!activeSource}
            onClose={closeSourceSchemasModal}
            title={activeSource ? `${activeSource.sourceName} schemas` : 'Schemas'}
            width={960}
        >
            <LemonTable
                dataSource={sourceSchemas}
                columns={sourceSchemaColumns}
                loading={sourceSchemasLoading}
                rowKey="schema_id"
                pagination={{ pageSize: 20 }}
                emptyState="No schemas are configured for this source."
            />
        </LemonModal>
    )
}
