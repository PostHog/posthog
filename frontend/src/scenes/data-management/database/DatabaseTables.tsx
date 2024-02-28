import { LemonButton, LemonDropdown, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { DatabaseTableListRow } from 'scenes/data-warehouse/types'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema'

import { DatabaseTable } from './DatabaseTable'

export function DatabaseTablesContainer(): JSX.Element {
    const { filteredTables, databaseLoading } = useValues(databaseTableListLogic)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <DatabaseTables
                tables={filteredTables}
                loading={databaseLoading}
                renderRow={(row: DatabaseTableListRow) => {
                    return (
                        <div className="px-4 py-3">
                            <div className="mt-2">
                                <span className="card-secondary">Columns</span>
                                <DatabaseTable table={row.name} tables={filteredTables} />
                                {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_VIEWS] && (
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
                                )}
                            </div>
                        </div>
                    )
                }}
            />
            <ViewLinkModal />
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

export function DatabaseTables<T extends DatabaseTableListRow>({
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
                                      const query: DataTableNode = {
                                          kind: NodeKind.DataTableNode,
                                          full: true,
                                          source: {
                                              kind: NodeKind.HogQLQuery,
                                              // TODO: Use `hogql` tag?
                                              query: `SELECT ${obj.columns
                                                  .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                                  .map(({ key }) => key)} FROM ${
                                                  table === 'numbers' ? 'numbers(0, 10)' : table
                                              } LIMIT 100`,
                                          },
                                      }
                                      return (
                                          <div className="flex">
                                              <Link to={urls.insightNew(undefined, undefined, JSON.stringify(query))}>
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
                                                      {obj.external_schema?.last_synced_at
                                                          ? humanFriendlyDetailedTime(
                                                                obj.external_schema?.last_synced_at
                                                            )
                                                          : 'Pending'}
                                                  </span>
                                              }
                                          >
                                              <span>
                                                  <LemonTag
                                                      type={obj.external_schema?.should_sync ? 'primary' : 'default'}
                                                      className="uppercase"
                                                  >
                                                      {obj.external_data_source
                                                          ? obj.external_data_source.source_type
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
