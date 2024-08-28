import { LemonButton, LemonDropdown, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { defaultQuery } from 'scenes/data-warehouse/utils'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { urls } from 'scenes/urls'

import { DatabaseSchemaTable } from '~/queries/schema'

import { DatabaseTable } from './DatabaseTable'

export function DatabaseTablesContainer(): JSX.Element {
    const { filteredTables, databaseLoading } = useValues(databaseTableListLogic)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)

    return (
        <>
            <DatabaseTables
                tables={filteredTables}
                loading={databaseLoading}
                renderRow={(row: DatabaseSchemaTable) => {
                    return (
                        <div className="px-4 py-3">
                            <div className="mt-2">
                                <span className="card-secondary">Columns</span>
                                <DatabaseTable table={row.name} tables={filteredTables} inEditSchemaMode={false} />
                                <div className="w-full flex justify-end">
                                    <LemonButton
                                        className="mt-2"
                                        type="primary"
                                        onClick={() => {
                                            selectSourceTable(row.name)
                                            toggleJoinTableModal()
                                        }}
                                    >
                                        Add link to view
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )
                }}
            />
        </>
    )
}

interface DatabaseTablesProps<T extends Record<string, any>> {
    tables: T[]
    loading: boolean
    renderRow: (row: T) => JSX.Element
    columns?: LemonTableColumns<T>
    extraColumns?: LemonTableColumns<T>
}

export function DatabaseTables<T extends DatabaseSchemaTable>({
    tables,
    loading,
    renderRow,
    columns,
    extraColumns = [],
}: DatabaseTablesProps<T>): JSX.Element {
    return (
        <>
            <LemonTable
                loading={loading}
                dataSource={tables}
                columns={
                    columns
                        ? [...columns, ...extraColumns]
                        : [
                              {
                                  title: 'Table',
                                  key: 'name',
                                  dataIndex: 'name',
                                  render: function RenderTable(table, obj: T) {
                                      const query = defaultQuery(table as string, Object.values(obj.fields))
                                      return (
                                          <div className="flex">
                                              <Link to={urls.insightNew(undefined, undefined, query)}>
                                                  <code>{table}</code>
                                              </Link>
                                          </div>
                                      )
                                  },
                              },
                              {
                                  title: 'Type',
                                  key: 'type',
                                  dataIndex: 'name',
                                  render: function RenderType(_, obj: T) {
                                      return (
                                          <LemonDropdown
                                              placement="top"
                                              showArrow
                                              trigger="hover"
                                              overlay={
                                                  <span>
                                                      Last synced:{' '}
                                                      {obj.type === 'data_warehouse' && obj.schema?.last_synced_at
                                                          ? humanFriendlyDetailedTime(obj.schema?.last_synced_at)
                                                          : 'Pending'}
                                                  </span>
                                              }
                                          >
                                              <span>
                                                  <LemonTag
                                                      type={
                                                          obj.type === 'data_warehouse' && obj.schema?.should_sync
                                                              ? 'primary'
                                                              : 'default'
                                                      }
                                                      className="uppercase"
                                                  >
                                                      {obj.type === 'data_warehouse' && obj.source
                                                          ? obj.source.source_type
                                                          : 'PostHog'}
                                                  </LemonTag>
                                              </span>
                                          </LemonDropdown>
                                      )
                                  },
                              },
                              ...extraColumns,
                          ]
                }
                expandable={{
                    expandedRowRender: renderRow,
                    rowExpandable: () => true,
                    noIndent: true,
                }}
            />
        </>
    )
}
