import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useActions, useValues } from 'kea'
import { databaseSceneLogic, DatabaseSceneRow } from 'scenes/data-management/database/databaseSceneLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonButton, LemonModal, LemonSelect, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { DatabaseTable } from './DatabaseTable'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

export function DatabaseTablesContainer(): JSX.Element {
    const { filteredTables, databaseLoading } = useValues(databaseSceneLogic)
    const { viewOptions, toJoinKeyOptions, selectedView, selectedTable, isFieldModalOpen, fromJoinKeyOptions } =
        useValues(viewLinkLogic)
    const { selectView, toggleFieldModal, selectTable } = useActions(viewLinkLogic)

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
                                <div className="w-full flex justify-end">
                                    <LemonButton
                                        className="mt-2"
                                        type="primary"
                                        onClick={() => {
                                            selectTable(row)
                                            toggleFieldModal()
                                        }}
                                    >
                                        Add Fields
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )
                }}
            />
            <LemonModal
                footer={
                    <>
                        <LemonButton type="secondary">Close</LemonButton>
                        <LemonButton type="primary">Save</LemonButton>
                    </>
                }
                title="Add Fields"
                description={
                    'Posthog models can be extended with custom fields based on views that have been created. These fields can be used in queries and accessible at the top level without needing to define joins.'
                }
                isOpen={isFieldModalOpen}
                onClose={toggleFieldModal}
                width={600}
            >
                <div className="flex flex-col w-full justify-between items-center">
                    <div className="flex flex-row w-full justify-between">
                        <div className="flex flex-col">
                            <span className="l4">Table</span>
                            {selectedTable ? selectedTable.name : ''}
                        </div>
                        <div>
                            <span className="l4">View</span>
                            <LemonSelect options={viewOptions} onSelect={selectView} />
                        </div>
                    </div>
                    <div className="mt-3 flex flex-row justify-between items-center w-full">
                        <div>
                            <span className="l4">Join Key</span>
                            <LemonSelect options={fromJoinKeyOptions} />
                        </div>
                        <div className="mt-5">
                            <IconSwapHoriz />
                        </div>
                        <div>
                            <span className="l4">Join Key</span>
                            <LemonSelect
                                disabledReason={selectedView ? '' : 'Select a view to choose join key'}
                                options={toJoinKeyOptions}
                                onSelect={() => {}}
                            />
                        </div>
                    </div>
                </div>
            </LemonModal>
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
                                                  .map(({ key }) => key)} FROM ${table} LIMIT 100`,
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
