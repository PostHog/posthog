import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useActions, useValues } from 'kea'
import { databaseSceneLogic, DatabaseSceneRow } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { DatabaseTable } from './DatabaseTable'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function DatabaseTablesContainer(): JSX.Element {
    const { filteredTables, databaseLoading } = useValues(databaseSceneLogic)
    const { toggleFieldModal, selectTable } = useActions(viewLinkLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <DatabaseTables
                tables={filteredTables}
                loading={databaseLoading}
                renderRow={(row: DatabaseSceneRow) => {
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
                                                selectTable(row)
                                                toggleFieldModal()
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
            <ViewLinkModal tableSelectable={false} />
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

export function DatabaseTables<T extends DatabaseSceneRow>({
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
                                  render: function RenderType() {
                                      return (
                                          <LemonTag type="default" className="uppercase">
                                              PostHog
                                          </LemonTag>
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
