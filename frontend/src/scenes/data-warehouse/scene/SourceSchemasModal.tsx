import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { sourceSchemasModalLogic } from './sourceSchemasModalLogic'
import { sourceSchemaColumns } from './warehouseStatusDisplay'

export function SourceSchemasModal(): JSX.Element {
    const { activeSource, sourceSchemas, sourceSchemasLoading, sourceSchemasError } = useValues(sourceSchemasModalLogic)
    const { closeSourceSchemasModal, loadSourceSchemas } = useActions(sourceSchemasModalLogic)

    return (
        <LemonModal
            isOpen={!!activeSource}
            onClose={closeSourceSchemasModal}
            title={activeSource ? `${activeSource.sourceName} schemas` : 'Schemas'}
            width={960}
        >
            {sourceSchemasError ? (
                <LemonBanner type="error">
                    <div className="flex items-center justify-between gap-3">
                        <span>Schemas could not be loaded.</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={() => activeSource && loadSourceSchemas(activeSource)}
                            loading={sourceSchemasLoading}
                        >
                            Try again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={sourceSchemas}
                    columns={sourceSchemaColumns}
                    loading={sourceSchemasLoading}
                    rowKey="schema_id"
                    pagination={{ pageSize: 20 }}
                    emptyState="No schemas are configured for this source."
                />
            )}
        </LemonModal>
    )
}
