import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

export interface TablePreviewProps {
    table: DatabaseSchemaTable | undefined
    emptyMessage: string
    previewData?: Record<string, any>[]
    loading?: boolean
    selectedKey?: string | null
}

export function TablePreview({
    table,
    emptyMessage,
    previewData = [],
    loading = false,
    selectedKey = null,
}: TablePreviewProps): JSX.Element {
    const columns: LemonTableColumns<Record<string, any>> = table
        ? Object.values(table.fields)
              .filter((column) => column.type !== 'view')
              .map((column) => {
                  const isSelectedKey = selectedKey === column.name
                  return {
                      key: column.name,
                      dataIndex: column.name,
                      className: isSelectedKey
                          ? 'bg-warning-highlight border-l-2 border-r-2 border-warning'
                          : undefined,
                      width: 120,
                      title: (
                          <div className="min-w-0 max-w-32">
                              <div className="font-medium text-xs truncate" title={column.name}>
                                  {column.name}
                              </div>
                              <div className="text-muted text-xxs">{column.type}</div>
                          </div>
                      ),
                      render: (value) => (
                          <div className="text-xs truncate max-w-32" title={String(value || '')}>
                              {value !== null && value !== undefined ? String(value) : '-'}
                          </div>
                      ),
                  }
              })
        : []

    return (
        <div className="flex-1 min-w-0">
            <div className="mt-2 border-t border-border rounded overflow-hidden h-64">
                {table ? (
                    <LemonTable
                        size="small"
                        className="w-full h-full"
                        embedded
                        loading={loading}
                        columns={columns}
                        dataSource={previewData}
                        rowKey={(_, index) => index}
                        emptyState={
                            loading ? null : (
                                <div className="text-muted text-sm text-center p-4">
                                    {previewData.length === 0 ? 'No data available' : 'Loading...'}
                                </div>
                            )
                        }
                    />
                ) : (
                    <div className="h-full flex items-center justify-center text-muted text-sm">{emptyMessage}</div>
                )}
            </div>
        </div>
    )
}
