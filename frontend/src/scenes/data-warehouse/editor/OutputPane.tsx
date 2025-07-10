import './DataGrid.scss'
import 'react-data-grid/lib/styles.css'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'
import DataGrid, { RenderHeaderCellProps, SortColumn } from 'react-data-grid'
import { DataGridProps } from 'react-data-grid'

import {
    IconBolt,
    IconBrackets,
    IconCode,
    IconCopy,
    IconDownload,
    IconExpand45,
    IconGear,
    IconGraph,
    IconMinus,
    IconPlus,
    IconShare,
} from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { JSONViewer } from 'lib/components/JSONViewer'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { LoadPreviewText } from '~/queries/nodes/DataNode/LoadNext'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { Table } from '~/queries/nodes/DataVisualization/Components/Table'
import { TableDisplay } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import { DataTableVisualizationProps } from '~/queries/nodes/DataVisualization/DataVisualization'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { HogQLQueryResponse } from '~/schema'
import { ChartDisplayType, ExporterFormat } from '~/types'

import TabScroller from './TabScroller'
import { FixErrorButton } from './components/FixErrorButton'
import { multitabEditorLogic } from './multitabEditorLogic'
import { OutputTab, outputPaneLogic } from './outputPaneLogic'
import { QueryInfo } from './sidebar/QueryInfo'
import { QueryVariables } from './sidebar/QueryVariables'

interface RowDetailsModalProps {
    isOpen: boolean
    onClose: () => void
    row: Record<string, any> | null
    columns: string[]
}

const CLICKHOUSE_TYPES = [
    'UUID',
    'String',
    'Nothing',
    'DateTime64',
    'DateTime32',
    'DateTime',
    'Date',
    'Date32',
    'UInt8',
    'UInt16',
    'UInt32',
    'UInt64',
    'Float8',
    'Float16',
    'Float32',
    'Float64',
    'Int8',
    'Int16',
    'Int32',
    'Int64',
    'Tuple',
    'Array',
    'Map',
    'Bool',
    'Decimal',
    'FixedString',
]

const cleanClickhouseType = (type: string | undefined): string | undefined => {
    if (!type) {
        return undefined
    }

    // Replace newline characters followed by empty space
    type = type.replace(/\n\s+/, '')

    if (type.startsWith('Nullable(')) {
        type = type.replace('Nullable(', '')
        type = type.substring(0, type.length - 1)
    }

    if (type.startsWith('Array(')) {
        const tokenifiedType = type.split(/(\W)/)
        type = tokenifiedType
            .filter((n) => {
                if (n === 'Nullable') {
                    return true
                }

                // Is a single character and not alpha-numeric
                if (n.length === 1 && !/^[a-z0-9]+$/i.test(n)) {
                    return true
                }

                return CLICKHOUSE_TYPES.includes(n)
            })
            .join('')
    }

    return type.replace(/\(.+\)+/, '')
}

function RowDetailsModal({ isOpen, onClose, row, columns }: RowDetailsModalProps): JSX.Element {
    const [showRawJson, setShowRawJson] = useState<Record<string, boolean>>({})
    const [wordWrap, setWordWrap] = useState<Record<string, boolean>>({})

    if (!row) {
        return <></>
    }

    const isJsonString = (str: string): boolean => {
        try {
            const parsed = JSON.parse(str)
            return typeof parsed === 'object' && parsed !== null
        } catch {
            return false
        }
    }

    const tableData = columns.map((column) => {
        const value = row[column]
        const isStringifiedJson = typeof value === 'string' && isJsonString(value)
        const isJson = typeof value === 'object' || isStringifiedJson
        const jsonValue = isStringifiedJson ? JSON.parse(value) : value

        return {
            column,
            isJson,
            rawValue:
                value === null
                    ? 'null'
                    : typeof value === 'object' || isStringifiedJson
                      ? JSON.stringify(value, null, 2)
                      : String(value),
            value:
                value === null ? (
                    <span className="text-muted">null</span>
                ) : isJson ? (
                    <div className="flex w-full gap-2">
                        <div className="w-full overflow-hidden">
                            {showRawJson[column] ? (
                                <pre
                                    className={clsx(
                                        'm-0 font-mono',
                                        wordWrap[column]
                                            ? 'whitespace-pre-wrap break-all'
                                            : 'hide-scrollbar overflow-x-auto'
                                    )}
                                >
                                    {String(value)}
                                </pre>
                            ) : (
                                <div className="max-w-full overflow-x-auto">
                                    <JSONViewer src={jsonValue} name={null} collapsed={1} />
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <span className="whitespace-pre-wrap break-all font-mono">{String(value)}</span>
                    </div>
                ),
        }
    })

    return (
        <LemonModal title="Row Details" isOpen={isOpen} onClose={onClose} width={800}>
            <div className="RowDetailsModal max-h-[70vh] overflow-y-auto overflow-x-hidden px-2">
                <LemonTable
                    dataSource={tableData}
                    className="w-full table-fixed"
                    columns={[
                        {
                            title: 'Column',
                            dataIndex: 'column',
                            className: 'font-semibold',
                            width: '35%',
                            render: (_, record) => <span title={record.column}>{record.column}</span>,
                        },
                        {
                            title: 'Value',
                            dataIndex: 'value',
                            className: 'px-4 overflow-hidden',
                            width: '65%',
                            render: (_, record) => (
                                <div className="flex w-full items-center gap-2">
                                    <div className="flex-1 overflow-x-auto pr-2">{record.value}</div>
                                    <div className="ml-auto flex flex-shrink-0 flex-row gap-1">
                                        {record.isJson && record.rawValue && record.rawValue != 'null' && (
                                            <LemonButton
                                                size="small"
                                                icon={<IconCode />}
                                                onClick={() =>
                                                    setShowRawJson((prev) => ({
                                                        ...prev,
                                                        [record.column]: !prev[record.column],
                                                    }))
                                                }
                                                tooltip={showRawJson[record.column] ? 'Show formatted' : 'Show raw'}
                                            />
                                        )}
                                        {showRawJson[record.column] && (
                                            <LemonButton
                                                size="small"
                                                icon={wordWrap[record.column] ? <IconMinus /> : <IconPlus />}
                                                onClick={() =>
                                                    setWordWrap((prev) => ({
                                                        ...prev,
                                                        [record.column]: !prev[record.column],
                                                    }))
                                                }
                                                tooltip={wordWrap[record.column] ? 'Collapse' : 'Expand'}
                                            />
                                        )}
                                        <LemonButton
                                            size="small"
                                            icon={<IconCopy />}
                                            onClick={() => void copyToClipboard(record.rawValue, 'value')}
                                            tooltip="Copy value"
                                        />
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}

export function OutputPane(): JSX.Element {
    const { activeTab } = useValues(outputPaneLogic)
    const { setActiveTab } = useActions(outputPaneLogic)
    const { editingView } = useValues(multitabEditorLogic)

    const {
        sourceQuery,
        exportContext,
        editorKey,
        editingInsight,
        updateInsightButtonEnabled,
        showLegacyFilters,
        localStorageResponse,
        queryInput,
    } = useValues(multitabEditorLogic)
    const { saveAsInsight, updateInsight, setSourceQuery, runQuery, shareTab } = useActions(multitabEditorLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const {
        response: dataNodeResponse,
        responseLoading,
        responseError,
        queryId,
        pollResponse,
    } = useValues(dataNodeLogic)
    const { queryCancelled } = useValues(dataVisualizationLogic)
    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const response = (dataNodeResponse ?? localStorageResponse) as HogQLQueryResponse | undefined

    const [progressCache, setProgressCache] = useState<Record<string, number>>({})

    const vizKey = useMemo(() => `SQLEditorScene`, [])

    const [selectedRow, setSelectedRow] = useState<Record<string, any> | null>(null)

    const setProgress = useCallback((loadId: string, progress: number) => {
        setProgressCache((prev) => ({ ...prev, [loadId]: progress }))
    }, [])

    const columns = useMemo(() => {
        const types = response?.types

        const baseColumns: DataGridProps<Record<string, any>>['columns'] = [
            {
                key: '__details',
                name: '',
                minWidth: 30,
                width: 30,
                renderCell: ({ row }: { row: any }) => (
                    <div className="hover-actions-cell flex items-center justify-center">
                        <LemonButton
                            size="xsmall"
                            icon={<IconExpand45 />}
                            onClick={(e) => {
                                e.stopPropagation()
                                setSelectedRow(row)
                            }}
                        />
                    </div>
                ),
            },
            ...(response?.columns?.map((column: string, index: number) => {
                const type = types?.[index]?.[1]

                const maxContentLength = Math.max(
                    column.length,
                    ...(response.results || (response as any).result).map((row: any[]) => {
                        const content = row[index]
                        return typeof content === 'string'
                            ? content.length
                            : content === null
                              ? 0
                              : content.toString().length
                    })
                )
                const isLongContent = maxContentLength > 100
                const finalWidth = isLongContent ? 600 : undefined

                const baseColumn: DataGridProps<Record<string, any>>['columns'][0] = {
                    key: column,
                    name: (
                        <>
                            {column}{' '}
                            {type && (
                                <span className="text-[10px] font-medium italic">{cleanClickhouseType(type)}</span>
                            )}
                        </>
                    ),
                    resizable: true,
                    sortable: true,
                    width: finalWidth,
                    headerCellClass: 'cursor-pointer',
                    renderHeaderCell: ({ column: col, sortDirection }: RenderHeaderCellProps<any>) => (
                        <div className="flex items-center justify-between py-2">
                            <span>{col.name}</span>
                            <div className="ml-1 flex flex-col">
                                <span
                                    className={`text-[7px] leading-none ${
                                        sortDirection === 'ASC' ? 'text-black-600' : 'text-gray-400'
                                    }`}
                                >
                                    ▲
                                </span>
                                <span
                                    className={`text-[7px] leading-none ${
                                        sortDirection === 'DESC' ? 'text-black-600' : 'text-gray-400'
                                    }`}
                                >
                                    ▼
                                </span>
                            </div>
                        </div>
                    ),
                }

                // Hack to get bools to render in the data grid
                if (type && type.indexOf('Bool') !== -1) {
                    return {
                        ...baseColumn,
                        renderCell: (props: any) => {
                            if (props.row[column] === null) {
                                return null
                            }
                            return props.row[column].toString()
                        },
                    }
                }

                return {
                    ...baseColumn,
                    renderCell: (props: any) => props.row[column],
                }
            }) ?? []),
        ]

        return baseColumns
    }, [response, setSelectedRow])

    const rows = useMemo(() => {
        if (!response?.results) {
            return []
        }

        let processedRows = response.results.map((row: any[], index: number) => {
            const rowObject: Record<string, any> = { __index: index }
            response.columns?.forEach((column: string, i: number) => {
                // Handling objects here as other viz methods can accept objects. Data grid does not for now
                if (typeof row[i] === 'object' && row[i] !== null) {
                    rowObject[column] = JSON.stringify(row[i])
                } else {
                    rowObject[column] = row[i]
                }
            })
            return rowObject
        })

        return processedRows
    }, [response])

    const hasColumns = columns.length > 1

    return (
        <div className="OutputPane flex w-full flex-1 flex-col bg-white dark:bg-black">
            <div className="align-center flex h-[50px] w-full flex-row justify-between overflow-y-auto">
                <div className="ml-4 flex h-[50px] gap-2">
                    {[
                        {
                            key: OutputTab.Results,
                            label: 'Results',
                            icon: <IconTableChart />,
                        },
                        {
                            key: OutputTab.Visualization,
                            label: 'Visualization',
                            icon: <IconGraph />,
                        },
                        ...(featureFlags[FEATURE_FLAGS.SQL_EDITOR_TREE_VIEW]
                            ? [
                                  {
                                      key: OutputTab.Variables,
                                      label: (
                                          <Tooltip
                                              title={editingView ? 'Variables are not allowed in views.' : undefined}
                                          >
                                              Variables
                                          </Tooltip>
                                      ),
                                      disabled: editingView,
                                      icon: <IconBrackets />,
                                  },
                                  {
                                      key: OutputTab.Materialization,
                                      label: 'Materialization',
                                      icon: <IconBolt />,
                                  },
                              ]
                            : []),
                    ].map((tab) => (
                        <div
                            key={tab.key}
                            className={clsx(
                                'bold flex flex-1 cursor-pointer flex-row content-center items-center border-b-[medium] px-2 pt-[3px]',
                                {
                                    '!border-brand-yellow font-semibold': tab.key === activeTab,
                                    'border-transparent': tab.key !== activeTab,
                                    'cursor-not-allowed opacity-50': tab.disabled,
                                }
                            )}
                            onClick={() => !tab.disabled && setActiveTab(tab.key)}
                        >
                            <span className="mr-1">{tab.icon}</span>
                            {tab.label}
                        </div>
                    ))}
                </div>
                <div className="flex gap-2 px-4 py-2">
                    {showLegacyFilters && (
                        <DateRange
                            key="date-range"
                            query={sourceQuery.source}
                            setQuery={(query) => {
                                setSourceQuery({
                                    ...sourceQuery,
                                    source: query,
                                })
                                runQuery(query.query)
                            }}
                        />
                    )}
                    {activeTab === OutputTab.Visualization && (
                        <>
                            <div className="flex flex-wrap justify-between">
                                <div className="flex items-center" />
                                <div className="flex items-center">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <TableDisplay
                                            disabledReason={!hasColumns ? 'No results to visualize' : undefined}
                                        />

                                        <LemonButton
                                            disabledReason={!hasColumns ? 'No results to visualize' : undefined}
                                            type="secondary"
                                            icon={<IconGear />}
                                            onClick={() => toggleChartSettingsPanel()}
                                            tooltip="Visualization settings"
                                        />
                                        {editingInsight && (
                                            <LemonButton
                                                disabledReason={!updateInsightButtonEnabled && 'No updates to save'}
                                                type="primary"
                                                onClick={() => updateInsight()}
                                                id="sql-editor-update-insight"
                                                sideAction={{
                                                    dropdown: {
                                                        placement: 'bottom-end',
                                                        overlay: (
                                                            <LemonMenuOverlay
                                                                items={[
                                                                    {
                                                                        label: 'Save as...',
                                                                        onClick: () => saveAsInsight(),
                                                                    },
                                                                ]}
                                                            />
                                                        ),
                                                    },
                                                }}
                                            >
                                                Save insight
                                            </LemonButton>
                                        )}
                                        {!editingInsight && (
                                            <LemonButton
                                                disabledReason={!hasColumns ? 'No results to save' : undefined}
                                                type="primary"
                                                onClick={() => saveAsInsight()}
                                                id="sql-editor-save-insight"
                                            >
                                                Save insight
                                            </LemonButton>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                    {activeTab === OutputTab.Results && (
                        <LemonButton
                            disabledReason={!hasColumns && !editingInsight ? 'No results to visualize' : undefined}
                            type="secondary"
                            onClick={() => setActiveTab(OutputTab.Visualization)}
                            id={`sql-editor-${editingInsight ? 'view' : 'create'}-insight`}
                            icon={<IconGraph />}
                        >
                            {editingInsight ? 'View insight' : 'Create insight'}
                        </LemonButton>
                    )}
                    {activeTab === OutputTab.Results && exportContext && (
                        <Tooltip title="Export the table results" className={!hasColumns ? 'hidden' : ''}>
                            <ExportButton
                                id="sql-editor-export"
                                disabledReason={!hasColumns ? 'No results to export' : undefined}
                                type="secondary"
                                icon={<IconDownload />}
                                sideIcon={null}
                                buttonCopy=""
                                items={[
                                    {
                                        export_format: ExporterFormat.CSV,
                                        export_context: exportContext,
                                    },
                                    {
                                        export_format: ExporterFormat.XLSX,
                                        export_context: exportContext,
                                    },
                                ]}
                            />
                        </Tooltip>
                    )}
                    {activeTab === OutputTab.Results && (
                        <Tooltip title="Share your current query">
                            <LemonButton
                                id="sql-editor-share"
                                disabledReason={!queryInput && 'No query to share'}
                                type="secondary"
                                icon={<IconShare />}
                                onClick={() => shareTab()}
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
            <div className="bg-dark relative flex flex-1">
                <Content
                    activeTab={activeTab}
                    responseError={responseError}
                    responseLoading={responseLoading}
                    response={response}
                    sourceQuery={sourceQuery}
                    queryCancelled={queryCancelled}
                    columns={columns}
                    rows={rows}
                    isDarkModeOn={isDarkModeOn}
                    vizKey={vizKey}
                    setSourceQuery={setSourceQuery}
                    exportContext={exportContext}
                    saveAsInsight={saveAsInsight}
                    queryId={queryId}
                    pollResponse={pollResponse}
                    editorKey={editorKey}
                    setProgress={setProgress}
                    progress={queryId ? progressCache[queryId] : undefined}
                />
            </div>
            <div className="flex justify-between border-t px-2">
                <div>
                    {response && !responseError ? <LoadPreviewText localResponse={localStorageResponse} /> : <></>}
                </div>
                <ElapsedTime />
            </div>
            <RowDetailsModal
                isOpen={!!selectedRow}
                onClose={() => setSelectedRow(null)}
                row={selectedRow}
                columns={response?.columns || []}
            />
        </div>
    )
}

function InternalDataTableVisualization(
    props: DataTableVisualizationProps & { onSaveInsight: () => void }
): JSX.Element | null {
    const { query, visualizationType, showEditingUI, response, responseLoading, isChartSettingsPanelOpen } =
        useValues(dataVisualizationLogic)

    let component: JSX.Element | null = null

    // TODO(@Gilbert09): Better loading support for all components - e.g. using the `loading` param of `Table`
    if (!showEditingUI && (!response || responseLoading)) {
        component = (
            <div className="bg-surface-primary flex h-full flex-1 flex-col items-center justify-center">
                <LoadingBar />
            </div>
        )
    } else if (visualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <Table
                uniqueKey={props.uniqueKey}
                query={query}
                context={props.context}
                cachedResults={props.cachedResults as HogQLQueryResponse | undefined}
            />
        )
    } else if (
        visualizationType === ChartDisplayType.ActionsLineGraph ||
        visualizationType === ChartDisplayType.ActionsBar ||
        visualizationType === ChartDisplayType.ActionsAreaGraph ||
        visualizationType === ChartDisplayType.ActionsStackedBar
    ) {
        component = <LineGraph />
    } else if (visualizationType === ChartDisplayType.BoldNumber) {
        component = <HogQLBoldNumber />
    }

    return (
        <div className="DataVisualization hide-scrollbar flex h-full flex-1 gap-2">
            <div className="relative flex w-full flex-1 flex-col gap-4">
                <div className="hide-scrollbar flex flex-1 flex-row gap-4 overflow-auto">
                    {isChartSettingsPanelOpen && (
                        <div>
                            <SideBar />
                        </div>
                    )}
                    <div className={clsx('h-full w-full flex-1 overflow-auto')}>{component}</div>
                </div>
            </div>
        </div>
    )
}

const ErrorState = ({ responseError, sourceQuery, queryCancelled, response }: any): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)

    const error = queryCancelled
        ? 'The query was cancelled'
        : response && 'error' in response && !!response.error
          ? response.error
          : responseError

    return (
        <div className={clsx('absolute bottom-0 left-0 right-0 top-0 flex-1 overflow-auto')}>
            <InsightErrorState
                query={sourceQuery}
                excludeDetail
                title={error}
                fixWithAIComponent={
                    featureFlags[FEATURE_FLAGS.SQL_EDITOR_AI_ERROR_FIXER] ? (
                        <FixErrorButton contentOverride="Fix error with AI" type="primary" source="query-error" />
                    ) : (
                        <></>
                    )
                }
            />
        </div>
    )
}

const Content = ({
    activeTab,
    responseError,
    responseLoading,
    response,
    sourceQuery,
    queryCancelled,
    columns,
    rows,
    isDarkModeOn,
    vizKey,
    editorKey,
    setSourceQuery,
    exportContext,
    saveAsInsight,
    queryId,
    pollResponse,
    setProgress,
    progress,
}: any): JSX.Element | null => {
    const [sortColumns, setSortColumns] = useState<SortColumn[]>([])
    const { editingView } = useValues(multitabEditorLogic)

    const sortedRows = useMemo(() => {
        if (!sortColumns.length) {
            return rows
        }

        return [...rows].sort((a, b) => {
            for (const { columnKey, direction } of sortColumns) {
                const aVal = a[columnKey]
                const bVal = b[columnKey]

                if (aVal === bVal) {
                    continue
                }
                if (aVal == null) {
                    return 1
                }
                if (bVal == null) {
                    return -1
                }

                const result = aVal < bVal ? -1 : 1
                return direction === 'DESC' ? -result : result
            }
            return 0
        })
    }, [rows, sortColumns])
    if (activeTab === OutputTab.Materialization) {
        return (
            <TabScroller>
                <div className="border-t px-6 py-4">
                    <QueryInfo codeEditorKey={editorKey} />
                </div>
            </TabScroller>
        )
    }

    if (activeTab === OutputTab.Variables) {
        if (editingView) {
            return (
                <TabScroller>
                    <div className="text-secondary border-t px-6 py-4">Variables are not allowed in views.</div>
                </TabScroller>
            )
        }
        return (
            <TabScroller>
                <div className="max-w-1/2 border-t px-6 py-4">
                    <QueryVariables />
                </div>
            </TabScroller>
        )
    }

    if (responseLoading) {
        return (
            <div className="flex w-full flex-1 items-center justify-center border-t p-2">
                <StatelessInsightLoadingState
                    queryId={queryId}
                    pollResponse={pollResponse}
                    setProgress={setProgress}
                    progress={progress}
                />
            </div>
        )
    }

    if (responseError) {
        return (
            <ErrorState
                responseError={responseError}
                sourceQuery={sourceQuery}
                queryCancelled={queryCancelled}
                response={response}
            />
        )
    }

    if (!response) {
        const msg =
            activeTab === OutputTab.Results
                ? 'Query results will appear here.'
                : 'Query results will be visualized here.'
        return (
            <div
                className="flex flex-1 items-center justify-center border-t"
                data-attr="sql-editor-output-pane-empty-state"
            >
                <span className="text-secondary mt-3">
                    {msg} Press <KeyboardShortcut command enter /> to run the query.
                </span>
            </div>
        )
    }

    if (activeTab === OutputTab.Results) {
        return (
            <TabScroller data-attr="sql-editor-output-pane-results">
                <DataGrid
                    className={isDarkModeOn ? 'rdg-dark h-full' : 'rdg-light h-full'}
                    columns={columns}
                    rows={sortedRows}
                    sortColumns={sortColumns}
                    onSortColumnsChange={setSortColumns}
                />
            </TabScroller>
        )
    }

    if (activeTab === OutputTab.Visualization) {
        return (
            <div className="hide-scrollbar absolute bottom-0 left-0 right-0 top-0 flex-1 border-t px-4 py-1">
                <InternalDataTableVisualization
                    uniqueKey={vizKey}
                    query={sourceQuery}
                    setQuery={setSourceQuery}
                    context={{}}
                    cachedResults={undefined}
                    exportContext={exportContext}
                    onSaveInsight={saveAsInsight}
                />
            </div>
        )
    }
    return null
}
