import 'react-data-grid/lib/styles.css'
import './DataGrid.scss'

import {
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
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { JSONViewer } from 'lib/components/JSONViewer'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useCallback, useMemo, useState } from 'react'
import DataGrid from 'react-data-grid'
import { DataGridProps } from 'react-data-grid'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { LoadPreviewText } from '~/queries/nodes/DataNode/LoadNext'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { Table } from '~/queries/nodes/DataVisualization/Components/Table'
import { TableDisplay } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import { DataTableVisualizationProps } from '~/queries/nodes/DataVisualization/DataVisualization'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { ChartDisplayType, ExporterFormat } from '~/types'

import { FixErrorButton } from './components/FixErrorButton'
import { multitabEditorLogic } from './multitabEditorLogic'
import { outputPaneLogic, OutputTab } from './outputPaneLogic'
import { QueryInfo } from './sidebar/QueryInfo'
import { QueryVariables } from './sidebar/QueryVariables'
import TabScroller from './TabScroller'

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
                    <div className="flex gap-2 w-full">
                        <div className="w-full overflow-hidden">
                            {showRawJson[column] ? (
                                <pre
                                    className={clsx(
                                        'm-0 font-mono',
                                        wordWrap[column]
                                            ? 'whitespace-pre-wrap break-all'
                                            : 'overflow-x-auto hide-scrollbar'
                                    )}
                                >
                                    {String(value)}
                                </pre>
                            ) : (
                                <div className="overflow-x-auto max-w-full">
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
            <div className="RowDetailsModal max-h-[70vh] overflow-y-auto px-2 overflow-x-hidden">
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
                                <div className="flex items-center gap-2 w-full">
                                    <div className="flex-1 overflow-x-auto pr-2">{record.value}</div>
                                    <div className="flex flex-row gap-1 flex-shrink-0 ml-auto">
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
                    <div className="hover-actions-cell flex justify-center items-center">
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

                const baseColumn = {
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
                    width: finalWidth,
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
        return response?.results?.map((row: any[], index: number) => {
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
    }, [response])

    const hasColumns = columns.length > 1

    return (
        <div className="OutputPane flex flex-col w-full flex-1 bg-white dark:bg-black">
            <div className="flex flex-row justify-between align-center w-full h-[50px] overflow-y-auto">
                <div className="flex h-[50px] gap-2 ml-4">
                    {[
                        {
                            key: OutputTab.Results,
                            label: 'Results',
                        },
                        {
                            key: OutputTab.Visualization,
                            label: 'Visualization',
                        },
                        ...(featureFlags[FEATURE_FLAGS.SQL_EDITOR_TREE_VIEW]
                            ? [
                                  {
                                      key: OutputTab.Variables,
                                      label: 'Variables',
                                  },
                                  {
                                      key: OutputTab.Materialization,
                                      label: 'Materialization',
                                  },
                              ]
                            : []),
                    ].map((tab) => (
                        <div
                            key={tab.key}
                            className={clsx(
                                'flex-1 bold content-center px-2 pt-[3px] cursor-pointer border-b-[medium]',
                                {
                                    'font-semibold !border-brand-yellow': tab.key === activeTab,
                                    'border-transparent': tab.key !== activeTab,
                                }
                            )}
                            onClick={() => setActiveTab(tab.key)}
                        >
                            {tab.label}
                        </div>
                    ))}
                </div>
                <div className="flex gap-2 py-2 px-4">
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
                            <div className="flex justify-between flex-wrap">
                                <div className="flex items-center" />
                                <div className="flex items-center">
                                    <div className="flex gap-2 items-center flex-wrap">
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
            <div className="flex flex-1 relative bg-dark">
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
            <div className="flex justify-between px-2 border-t">
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
            <div className="flex flex-col flex-1 justify-center items-center bg-surface-primary h-full">
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
        <div className="DataVisualization h-full hide-scrollbar flex flex-1 gap-2">
            <div className="relative w-full flex flex-col gap-4 flex-1">
                <div className="flex flex-1 flex-row gap-4 overflow-scroll hide-scrollbar">
                    {isChartSettingsPanelOpen && (
                        <div>
                            <SideBar />
                        </div>
                    )}
                    <div className={clsx('w-full h-full flex-1 overflow-auto')}>{component}</div>
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
        <div className={clsx('flex-1 absolute top-0 left-0 right-0 bottom-0 overflow-scroll')}>
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
    if (activeTab === OutputTab.Materialization) {
        return (
            <TabScroller>
                <div className="px-6 py-4 border-t">
                    <QueryInfo codeEditorKey={editorKey} />
                </div>
            </TabScroller>
        )
    }

    if (activeTab === OutputTab.Variables) {
        return (
            <TabScroller>
                <div className="px-6 py-4 border-t max-w-1/2">
                    <QueryVariables />
                </div>
            </TabScroller>
        )
    }

    if (responseLoading) {
        return (
            <div className="flex flex-1 p-2 w-full justify-center items-center border-t">
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
                className="flex flex-1 justify-center items-center border-t"
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
                    rows={rows}
                />
            </TabScroller>
        )
    }

    if (activeTab === OutputTab.Visualization) {
        return (
            <div className="flex-1 absolute top-0 left-0 right-0 bottom-0 px-4 py-1 hide-scrollbar border-t">
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
