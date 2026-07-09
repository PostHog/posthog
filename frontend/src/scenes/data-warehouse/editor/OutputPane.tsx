import './DataGrid.scss'
import 'react-data-grid/lib/styles.css'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'
import DataGrid, { DataGridProps, RenderHeaderCellProps, SortColumn } from 'react-data-grid'

import {
    IconCode,
    IconColumns,
    IconCopy,
    IconDownload,
    IconExpand45,
    IconGear,
    IconGraph,
    IconMinus,
    IconPlus,
    IconShare,
    IconScreen,
    IconWarning,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonMenu, LemonModal, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { JSONViewer } from 'lib/components/JSONViewer'
import { MCPUseCaseCard } from 'lib/components/MCPHint/MCPUseCaseCard'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { LoadPreviewText } from '~/queries/nodes/DataNode/LoadNext'
import { QueryExecutionDetails } from '~/queries/nodes/DataNode/QueryExecutionDetails'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { PieChart } from '~/queries/nodes/DataVisualization/Components/Charts/PieChart'
import { TwoDimensionalHeatmap } from '~/queries/nodes/DataVisualization/Components/Heatmap/TwoDimensionalHeatmap'
import { seriesBreakdownLogic } from '~/queries/nodes/DataVisualization/Components/seriesBreakdownLogic'
import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { Table } from '~/queries/nodes/DataVisualization/Components/Table'
import { TableDisplay } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import { DataTableVisualizationProps } from '~/queries/nodes/DataVisualization/DataVisualization'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { renderHogQLX } from '~/queries/nodes/HogQLX/render'
import { type DataTableNode, type HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ChartDisplayType,
    ExporterFormat,
    type ExportContext,
} from '~/types'

import { WarehouseWizardHint } from 'products/data_warehouse/frontend/shared/components/WarehouseWizardHint'

import {
    copyTableToCsv,
    copyTableToExcel,
    copyTableToJson,
    copyTableToMarkdown,
} from '../../../queries/nodes/DataTable/clipboardUtils'
import { FixErrorButton } from './components/FixErrorButton'
import { OutputTab, outputPaneLogic } from './outputPaneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'
import { trimRedundantTail } from './syncWarnings'
import TabScroller from './TabScroller'

interface RowDetailsModalProps {
    isOpen: boolean
    onClose: () => void
    row: Record<string, any> | null
    columns: string[]
    columnKeys: string[]
}

const ONE_DAY_IN_MILLISECONDS = 24 * 60 * 60 * 1000

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

const copyMap = {
    [ExporterFormat.CSV]: {
        label: 'CSV',
        copyFn: copyTableToCsv,
    },
    [ExporterFormat.JSON]: {
        label: 'JSON',
        copyFn: copyTableToJson,
    },
    [ExporterFormat.XLSX]: {
        label: 'Excel',
        copyFn: copyTableToExcel,
    },
    [ExporterFormat.MARKDOWN]: {
        label: 'Markdown',
        copyFn: copyTableToMarkdown,
    },
}

const createDataTableQuery = (): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: '',
    },
})

interface OutputTabConfig {
    key: OutputTab
    label: string
    icon: JSX.Element
}

const outputTabs: OutputTabConfig[] = [
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

const isDateTimeType = (type: string | undefined): boolean => {
    const cleanedType = cleanClickhouseType(type)
    return cleanedType === 'DateTime' || cleanedType === 'DateTime32' || cleanedType === 'DateTime64'
}

function RowDetailsModal({ isOpen, onClose, row, columns, columnKeys }: RowDetailsModalProps): JSX.Element {
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

    const tableData = columns.map((column, index) => {
        const columnKey = columnKeys[index]
        const value = row[columnKey]
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
                                    <JSONViewer src={jsonValue} name={null} collapsed={1} sortKeys={true} />
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

interface OutputTabLabelProps {
    tab: OutputTabConfig
    active: boolean
    onClick?: () => void
}

function OutputTabLabel({ tab, active, onClick }: OutputTabLabelProps): JSX.Element {
    return (
        <div
            className={clsx(
                'flex-1 flex-row flex items-center bold content-center px-2 pt-[3px] border-b-[medium] whitespace-nowrap',
                {
                    'font-semibold !border-brand-yellow': active,
                    'border-transparent': !active,
                    'cursor-pointer': !!onClick,
                    'cursor-default': !onClick,
                }
            )}
            onClick={onClick}
        >
            <span className="mr-1">{tab.icon}</span>
            {tab.label}
        </div>
    )
}

interface SplitOutputToggleProps {
    splitView: boolean
    onClick: () => void
}

function SplitOutputToggle({ splitView, onClick }: SplitOutputToggleProps): JSX.Element {
    return (
        <LemonButton
            active={splitView}
            className="self-center"
            type="secondary"
            size="small"
            icon={splitView ? <IconScreen /> : <IconColumns />}
            onClick={onClick}
            tooltip={splitView ? 'Show one output at a time' : 'Show results and visualization side by side'}
            data-attr="sql-editor-output-split-toggle"
        />
    )
}

interface VisualizationActionsProps {
    hasColumns: boolean
    settingsOpen: boolean
    onToggleChartSettingsPanel: () => void
}

function VisualizationActions({
    hasColumns,
    settingsOpen,
    onToggleChartSettingsPanel,
}: VisualizationActionsProps): JSX.Element {
    return (
        <div className="flex justify-end flex-wrap">
            <div className="flex gap-2 items-center flex-wrap">
                <TableDisplay disabledReason={!hasColumns ? 'No results to visualize' : undefined} />

                <LemonButton
                    disabledReason={!hasColumns ? 'No results to visualize' : undefined}
                    type={settingsOpen ? 'primary' : 'secondary'}
                    icon={<IconGear />}
                    size="small"
                    onClick={onToggleChartSettingsPanel}
                    tooltip="Visualization settings"
                    data-attr="sql-editor-visualization-settings-button"
                />
            </div>
        </div>
    )
}

/**
 * Transforms DataTable format back to DataTableRow format for clipboard operations
 */
function transformDataTableToDataTableRows(rows: Record<string, any>[], columns: string[]): DataTableRow[] {
    if (!columns.length || !rows.length) {
        return []
    }

    return rows.map((row) => ({
        result: columns.map((col, index) => {
            // Handle both direct column access and column_index format
            const columnKey = `${col}_${index}`
            return row[columnKey] !== undefined ? row[columnKey] : row[col]
        }),
    }))
}

interface ResultsActionsProps {
    response: HogQLQueryResponse | undefined
    rows: Record<string, any>[]
    hasColumns: boolean
    exportContext: ExportContext | undefined
    hasQueryInput: boolean
    isEmbeddedMode: boolean
    onShareTab?: () => void
}

function ResultsActions({
    response,
    rows,
    hasColumns,
    exportContext,
    hasQueryInput,
    isEmbeddedMode,
    onShareTab,
}: ResultsActionsProps): JSX.Element {
    // Copying or exporting results requires editor access to the export resource.
    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )

    return (
        <>
            <LemonMenu
                items={Object.values(copyMap).map(({ label, copyFn }) => ({
                    label,
                    onClick: () => {
                        if (response?.columns && rows.length > 0) {
                            const dataTableRows = transformDataTableToDataTableRows(rows, response.columns)
                            const query = createDataTableQuery()
                            copyFn(dataTableRows, response.columns, query)
                        }
                    },
                }))}
                placement="bottom-end"
            >
                <LemonButton
                    id="sql-editor-copy-dropdown"
                    disabledReason={
                        (!response?.columns || !rows.length ? 'No results to copy' : undefined) ??
                        exportAccessControlDisabledReason ??
                        undefined
                    }
                    type="secondary"
                    size="small"
                    icon={<IconCopy />}
                />
            </LemonMenu>
            {exportContext && (
                <Tooltip title="Export the table results" className={!hasColumns ? 'hidden' : ''}>
                    <ExportButton
                        id="sql-editor-export"
                        disabledReason={!hasColumns ? 'No results to export' : undefined}
                        type="secondary"
                        icon={<IconDownload />}
                        sideIcon={null}
                        buttonCopy=""
                        size="small"
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
            {!isEmbeddedMode && onShareTab && (
                <Tooltip title="Share your current query">
                    <LemonButton
                        id="sql-editor-share"
                        disabledReason={!hasQueryInput && 'No query to share'}
                        type="secondary"
                        size="small"
                        icon={<IconShare />}
                        onClick={onShareTab}
                    />
                </Tooltip>
            )}
        </>
    )
}

interface OutputActionsProps {
    activeTab: OutputTab
    response: HogQLQueryResponse | undefined
    rows: Record<string, any>[]
    hasColumns: boolean
    exportContext: ExportContext | undefined
    hasQueryInput: boolean
    isEmbeddedMode: boolean
    settingsOpen: boolean
    onShareTab?: () => void
    onToggleChartSettingsPanel: () => void
}

function OutputActions({
    activeTab,
    response,
    rows,
    hasColumns,
    exportContext,
    hasQueryInput,
    isEmbeddedMode,
    settingsOpen,
    onShareTab,
    onToggleChartSettingsPanel,
}: OutputActionsProps): JSX.Element | null {
    if (activeTab === OutputTab.Visualization) {
        return (
            <VisualizationActions
                hasColumns={hasColumns}
                settingsOpen={settingsOpen}
                onToggleChartSettingsPanel={onToggleChartSettingsPanel}
            />
        )
    }

    if (activeTab === OutputTab.Results) {
        return (
            <ResultsActions
                response={response}
                rows={rows}
                hasColumns={hasColumns}
                exportContext={exportContext}
                hasQueryInput={hasQueryInput}
                isEmbeddedMode={isEmbeddedMode}
                onShareTab={onShareTab}
            />
        )
    }

    return null
}

interface OutputPaneProps {
    tabId: string
    showToolbar?: boolean
    onShareTab?: () => void
}

export function OutputPane({ tabId, showToolbar = true, onShareTab }: OutputPaneProps): JSX.Element {
    const { activeTab } = useValues(outputPaneLogic)
    const { setActiveTab } = useActions(outputPaneLogic)

    const { sourceQuery, exportContext, insightLoading, hasQueryInput, isEmbeddedMode } = useValues(sqlEditorLogic)
    const { setSourceQuery } = useActions(sqlEditorLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const {
        response: dataNodeResponse,
        responseLoading,
        responseError,
        queryId,
        pollResponse,
    } = useValues(dataNodeLogic)
    const { queryCancelled, isChartSettingsPanelOpen } = useValues(dataVisualizationLogic)
    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)

    const response = dataNodeResponse as HogQLQueryResponse | undefined
    const splitPaneRef = useRef<HTMLDivElement>(null)
    const splitView = activeTab === OutputTab.Both
    const splitResizerProps = useMemo<ResizerLogicProps>(
        () => ({
            containerRef: splitPaneRef,
            logicKey: `sql-editor-output-split-${tabId || 'default'}`,
            placement: 'right' as const,
        }),
        [tabId]
    )
    const { desiredSize: splitPaneDesiredWidth } = useValues(resizerLogic(splitResizerProps))

    const [progressCache, setProgressCache] = useState<Record<string, number>>({})

    const vizKey = useMemo(() => `SQLEditorScene`, [])

    const [selectedRow, setSelectedRow] = useState<Record<string, any> | null>(null)

    const setProgress = useCallback((loadId: string, progress: number) => {
        setProgressCache((prev) => ({ ...prev, [loadId]: progress }))
    }, [])

    const toggleVisualizationSettingsPanel = useCallback(() => {
        toggleChartSettingsPanel()
    }, [toggleChartSettingsPanel])

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
                const isDateTimeColumn = isDateTimeType(type)

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
                    key: `${column}_${index}`,
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
                            <div className="flex flex-col ml-1">
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
                            const columnKey = `${column}_${index}`
                            if (props.row[columnKey] === null) {
                                return null
                            }
                            return props.row[columnKey].toString()
                        },
                    }
                }

                return {
                    ...baseColumn,
                    renderCell: (props: any) => {
                        const columnKey = `${column}_${index}`
                        const value = props.row[columnKey]
                        if (typeof value === 'string' && value.startsWith('["__hx_tag",') && value.endsWith(']')) {
                            try {
                                const parsedHogQLX = JSON.parse(value)
                                return renderHogQLX(parsedHogQLX)
                            } catch (e) {
                                console.error('Error parsing HogQLX value:', e)
                                return <span className="text-red">Error parsing value</span>
                            }
                        }

                        if (isDateTimeColumn && typeof value === 'string' && value) {
                            return <TZLabel time={value} timestampStyle="absolute" />
                        }

                        return value
                    },
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
                const columnKey = `${column}_${i}`
                // Handling objects here as other viz methods can accept objects. Data grid does not for now
                if (typeof row[i] === 'object' && row[i] !== null) {
                    rowObject[columnKey] = JSON.stringify(row[i])
                } else {
                    rowObject[columnKey] = row[i]
                }
            })
            return rowObject
        })

        return processedRows
    }, [response])

    const hasColumns = columns.length > 1
    const splitPaneWidth = splitPaneDesiredWidth ? `${Math.max(splitPaneDesiredWidth, 256)}px` : '50%'
    const splitToggle = (
        <SplitOutputToggle
            splitView={splitView}
            onClick={() => setActiveTab(splitView ? OutputTab.Results : OutputTab.Both)}
        />
    )
    const sharedContentProps = {
        responseError,
        responseLoading,
        response,
        insightLoading,
        sourceQuery,
        queryCancelled,
        columns,
        rows,
        isDarkModeOn,
        vizKey,
        setSourceQuery,
        exportContext,
        queryId,
        pollResponse,
        setProgress,
        progress: queryId ? progressCache[queryId] : undefined,
        showVisualizationSettings: showToolbar && isChartSettingsPanelOpen,
        isEmbeddedMode,
    }
    const sharedActionsProps = {
        response,
        rows,
        hasColumns,
        exportContext,
        hasQueryInput,
        isEmbeddedMode,
        settingsOpen: isChartSettingsPanelOpen,
        onShareTab,
        onToggleChartSettingsPanel: toggleVisualizationSettingsPanel,
    }

    const outputContent = splitView ? (
        <div className="flex flex-1 min-h-0 bg-dark">
            <div
                ref={splitPaneRef}
                className="relative flex min-w-64 flex-col bg-white dark:bg-black"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: splitPaneWidth, maxWidth: 'calc(100% - 16rem)' }}
            >
                {showToolbar ? (
                    <div className="flex flex-row justify-between align-center w-full min-h-[41px] overflow-y-auto border-r">
                        <div className="flex min-h-[41px] gap-2 ml-4">
                            {splitToggle}
                            <OutputTabLabel tab={outputTabs[0]} active />
                        </div>
                        <div className="flex gap-2 py-1 px-4 flex-shrink-0">
                            <OutputActions activeTab={OutputTab.Results} {...sharedActionsProps} />
                        </div>
                    </div>
                ) : null}
                <div className="flex flex-1 min-h-0 relative bg-dark border-r">
                    <Content activeTab={OutputTab.Results} {...sharedContentProps} />
                </div>
                <Resizer {...splitResizerProps} />
            </div>
            <div className="flex min-w-0 flex-1 flex-col bg-white dark:bg-black">
                {showToolbar ? (
                    <div className="flex flex-row justify-between align-center w-full min-h-[41px] overflow-y-auto">
                        <div className="flex min-h-[41px] gap-2 ml-4">
                            <OutputTabLabel tab={outputTabs[1]} active />
                        </div>
                        <div className="flex gap-2 py-1 px-4 flex-shrink-0">
                            <OutputActions activeTab={OutputTab.Visualization} {...sharedActionsProps} />
                        </div>
                    </div>
                ) : null}
                <div className="flex flex-1 min-h-0 relative bg-dark">
                    <Content activeTab={OutputTab.Visualization} {...sharedContentProps} />
                </div>
            </div>
        </div>
    ) : (
        <>
            {showToolbar ? (
                <div className="flex flex-row justify-between align-center w-full min-h-[41px] overflow-y-auto">
                    <div className="flex min-h-[41px] gap-2 ml-4">
                        {splitToggle}
                        {outputTabs.map((tab) => (
                            <OutputTabLabel
                                key={tab.key}
                                tab={tab}
                                active={tab.key === activeTab}
                                onClick={() => setActiveTab(tab.key)}
                            />
                        ))}
                    </div>
                    <div className="flex gap-2 py-1 px-4 flex-shrink-0">
                        <OutputActions activeTab={activeTab} {...sharedActionsProps} />
                    </div>
                </div>
            ) : null}
            <div className="flex flex-1 min-h-0 relative bg-dark">
                <Content activeTab={activeTab} {...sharedContentProps} />
            </div>
        </>
    )

    return (
        <div className="OutputPane flex flex-col w-full flex-1 min-h-0 bg-white dark:bg-black">
            {outputContent}
            <div className="flex justify-between px-2 border-t">
                <div>{response && !responseError ? <LoadPreviewText localResponse={response} /> : <></>}</div>
                <div className="flex items-center gap-4">
                    <ElapsedTime />
                    <QueryExecutionDetails />
                </div>
            </div>
            <RowDetailsModal
                isOpen={!!selectedRow}
                onClose={() => setSelectedRow(null)}
                row={selectedRow}
                columns={response?.columns || []}
                columnKeys={response?.columns?.map((column: string, index: number) => `${column}_${index}`) || []}
            />
        </div>
    )
}

function InternalDataTableVisualization(
    props: DataTableVisualizationProps & { showSettingsPanel: boolean }
): JSX.Element | null {
    const {
        query,
        effectiveVisualizationType,
        response,
        responseLoading,
        xData,
        yData,
        chartSettings,
        dashboardId,
        dataVisualizationProps,
        presetChartHeight,
    } = useValues(dataVisualizationLogic)

    const { seriesBreakdownData } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { goalLines } = useValues(displayLogic)

    let component: JSX.Element | null = null

    // TODO(@Gilbert09): Better loading support for all components - e.g. using the `loading` param of `Table`
    if (!response || responseLoading) {
        component = (
            <div className="flex flex-col flex-1 justify-center items-center bg-surface-primary h-full">
                <LoadingBar />
            </div>
        )
    } else if (effectiveVisualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <Table
                uniqueKey={props.uniqueKey}
                query={query}
                context={props.context}
                cachedResults={props.cachedResults as HogQLQueryResponse | undefined}
                embedded
            />
        )
    } else if (
        effectiveVisualizationType === ChartDisplayType.ActionsLineGraph ||
        effectiveVisualizationType === ChartDisplayType.ActionsBar ||
        effectiveVisualizationType === ChartDisplayType.ActionsAreaGraph ||
        effectiveVisualizationType === ChartDisplayType.ActionsStackedBar
    ) {
        const _xData = seriesBreakdownData.xData.data.length ? seriesBreakdownData.xData : xData
        const _yData = seriesBreakdownData.xData.data.length ? seriesBreakdownData.seriesData : yData
        component = (
            <LineGraph
                className="p-2"
                xData={_xData}
                yData={_yData}
                visualizationType={effectiveVisualizationType}
                chartSettings={chartSettings}
                dashboardId={dashboardId}
                goalLines={goalLines}
                presetChartHeight={presetChartHeight}
            />
        )
    } else if (effectiveVisualizationType === ChartDisplayType.ActionsPie) {
        const _xData = seriesBreakdownData.xData.data.length ? seriesBreakdownData.xData : xData
        const _yData = seriesBreakdownData.seriesData.length ? seriesBreakdownData.seriesData : yData

        component = (
            <PieChart
                className="p-2"
                uniqueKey={props.uniqueKey?.toString() ?? dataVisualizationProps.key}
                xData={_xData}
                yData={_yData}
                chartSettings={chartSettings}
                presetChartHeight={presetChartHeight}
            />
        )
    } else if (effectiveVisualizationType === ChartDisplayType.TwoDimensionalHeatmap) {
        component = <TwoDimensionalHeatmap />
    } else if (effectiveVisualizationType === ChartDisplayType.BoldNumber) {
        component = <HogQLBoldNumber />
    }

    if (props.embedded && !props.showSettingsPanel) {
        return <div className="DataVisualization InsightCard__viz">{component}</div>
    }

    return (
        <div className="DataVisualization h-full hide-scrollbar flex flex-1 gap-2">
            <div className="relative w-full flex flex-col gap-4 flex-1">
                <div className="flex flex-1 flex-row overflow-auto hide-scrollbar">
                    {props.showSettingsPanel && (
                        <>
                            <SideBar />
                            <LemonDivider vertical className="h-full" />
                        </>
                    )}
                    <div className={clsx('w-full h-full flex-1 overflow-auto')}>{component}</div>
                </div>
            </div>
        </div>
    )
}

const SyncWarningsBanner = ({ warnings }: { warnings?: HogQLQueryResponse['warnings'] }): JSX.Element | null => {
    if (!warnings || warnings.length === 0) {
        return null
    }
    return (
        <LemonBanner type="warning" className="m-2 flex-shrink-0" data-attr="sql-editor-output-pane-sync-warnings">
            Some warehouse sources used by this query are out of date — results may not reflect current data:
            <ul className="list-disc pl-5">
                {warnings.map((warning, index) => (
                    <li key={`${warning.table_name}-${warning.schema_name}-${index}`}>
                        {trimRedundantTail(warning.message)}
                        {warning.source_id && (
                            <>
                                {' '}
                                <Link to={urls.dataWarehouseSource(`managed-${warning.source_id}`)} target="_blank">
                                    Manage source
                                </Link>
                            </>
                        )}
                    </li>
                ))}
            </ul>
        </LemonBanner>
    )
}

const ErrorState = ({ responseError, sourceQuery, queryCancelled, response }: any): JSX.Element | null => {
    const error = queryCancelled
        ? 'The query was cancelled'
        : response && 'error' in response && !!response.error
          ? response.error
          : responseError

    return (
        <div className={clsx('flex-1 absolute top-0 left-0 right-0 bottom-0 overflow-auto')}>
            <div className="flex min-h-full flex-col justify-center">
                <InsightErrorState
                    query={sourceQuery}
                    excludeDetail
                    title={
                        <pre className="text-xs bg-danger-highlight p-2 rounded overflow-auto max-h-40 max-w-[80%] mx-auto text-left whitespace-pre-wrap break-words">
                            {error}
                        </pre>
                    }
                    excludeActions={queryCancelled} // Don't display fix/debugger buttons if the query was cancelled
                    fixWithAIComponent={
                        <FixErrorButton contentOverride="Fix error with AI" type="primary" source="query-error" />
                    }
                />
            </div>
        </div>
    )
}

const EmptyResultsState = (): JSX.Element => {
    return (
        <div
            className="flex flex-1 justify-center items-center gap-2 border-t px-4 py-6 text-center"
            data-attr="sql-editor-output-pane-no-rows-state"
        >
            <IconWarning className="text-warning text-lg" />
            <span className="text-secondary">Query produced no results</span>
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
    setSourceQuery,
    exportContext,
    queryId,
    pollResponse,
    setProgress,
    progress,
    insightLoading,
    showVisualizationSettings,
    isEmbeddedMode,
}: any): JSX.Element | null => {
    const [sortColumns, setSortColumns] = useState<SortColumn[]>([])

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
    const hasError = queryCancelled || !!responseError || !!(response && 'error' in response && !!response.error)

    if (hasError) {
        return (
            <ErrorState
                responseError={responseError}
                sourceQuery={sourceQuery}
                queryCancelled={queryCancelled}
                response={response}
            />
        )
    }

    if (activeTab === OutputTab.Visualization) {
        if (!response && !responseLoading && !insightLoading) {
            return (
                <div
                    className="flex flex-1 flex-col justify-center items-center border-t gap-4 p-4"
                    data-attr="sql-editor-output-pane-empty-state"
                >
                    <span className="text-secondary">
                        Query results will be visualized here. Press <KeyboardShortcut command enter /> to run the
                        query.
                    </span>
                    <WarehouseWizardHint
                        className="max-w-140"
                        fallback={
                            <MCPUseCaseCard
                                surfaceKey="sql.execute"
                                expiresAfterMs={ONE_DAY_IN_MILLISECONDS}
                                className="max-w-140"
                            />
                        }
                    />
                </div>
            )
        }

        return (
            <div className="absolute inset-0 flex flex-col border-t overflow-hidden">
                <SyncWarningsBanner warnings={response?.warnings} />
                <div className="flex flex-col flex-1 min-h-0 hide-scrollbar overflow-auto">
                    <InternalDataTableVisualization
                        uniqueKey={vizKey}
                        query={sourceQuery}
                        setQuery={setSourceQuery}
                        context={{}}
                        cachedResults={undefined}
                        exportContext={exportContext}
                        editMode
                        embedded={isEmbeddedMode}
                        showSettingsPanel={showVisualizationSettings}
                    />
                </div>
            </div>
        )
    }

    if (responseLoading || insightLoading) {
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

    if (!response) {
        const msg =
            activeTab === OutputTab.Results
                ? 'Query results will appear here.'
                : 'Query results will be visualized here.'
        return (
            <div
                className="flex flex-1 flex-col justify-center items-center border-t px-4 py-6 gap-4 text-center"
                data-attr="sql-editor-output-pane-empty-state"
            >
                <span className="text-secondary max-w-xl">
                    {msg} Press <KeyboardShortcut command enter /> to run the query at your cursor. Separate multiple
                    statements with <code>;</code> to run them independently.
                </span>
                <WarehouseWizardHint
                    className="max-w-140"
                    fallback={
                        <MCPUseCaseCard
                            surfaceKey="sql.execute"
                            expiresAfterMs={ONE_DAY_IN_MILLISECONDS}
                            className="max-w-140"
                        />
                    }
                />
            </div>
        )
    }

    if (activeTab === OutputTab.Results) {
        return (
            <div className="flex flex-col flex-1 min-h-0 w-full overflow-hidden">
                <SyncWarningsBanner warnings={response?.warnings} />
                {rows.length === 0 ? (
                    <EmptyResultsState />
                ) : (
                    <TabScroller data-attr="sql-editor-output-pane-results">
                        <DataGrid
                            className={clsx(isDarkModeOn ? 'rdg-dark h-full' : 'rdg-light h-full', 'ph-no-capture')}
                            columns={columns}
                            rows={sortedRows}
                            sortColumns={sortColumns}
                            onSortColumnsChange={setSortColumns}
                        />
                    </TabScroller>
                )}
            </div>
        )
    }
    return null
}
