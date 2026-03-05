import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

const columns: LemonTableColumns<DatabaseSchemaField> = [
    {
        title: 'Name',
        dataIndex: 'name',
        key: 'name',
    },
    {
        title: 'Type',
        dataIndex: 'type',
        key: 'type',
    },
    {
        title: 'Stats',
        key: 'stats',
        render: function RenderStats() {
            return (
                <Tooltip title="Coming soon">
                    <span className="text-muted">—</span>
                </Tooltip>
            )
        },
    },
]

export function NodeDetailColumns({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const logicProps = { id }
    const { savedQuery, savedQueryLoading } = useValues(nodeDetailSceneLogic(logicProps))

    const schemaColumns = savedQuery?.columns ?? []

    return (
        <div className="flex flex-col gap-2">
            <h3 className="text-base font-semibold mb-0">Columns</h3>
            <div className="max-h-80 overflow-y-auto">
                <LemonTable
                    dataSource={schemaColumns}
                    columns={columns}
                    loading={savedQueryLoading}
                    size="small"
                    rowKey="name"
                    emptyState="No columns available"
                />
            </div>
        </div>
    )
}
