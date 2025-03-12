import 'react-data-grid/lib/styles.css'
import './DataGrid.scss'

import { IconExpand, IconGear } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { useCallback, useMemo, useState } from 'react'
import DataGrid, { CellClickArgs } from 'react-data-grid'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
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

import { multitabEditorLogic } from './multitabEditorLogic'
import { outputPaneLogic, OutputTab } from './outputPaneLogic'
import { InfoTab } from './OutputPaneTabs/InfoTab'
import { LineageTab } from './OutputPaneTabs/lineageTab'
import { lineageTabLogic } from './OutputPaneTabs/lineageTabLogic'
import TabScroller from './OutputPaneTabs/TabScroller'

interface ExpandableCellProps {
    value: any
    columnName: string
    isExpanded: boolean
    onToggleExpand: () => void
    hasManualWidth: boolean
}

export function ExpandableCell({
    value,
    columnName,
    isExpanded,
    onToggleExpand,
    hasManualWidth,
}: ExpandableCellProps): JSX.Element {
    const [isHovered, setIsHovered] = useState(false)

    return (
        <div
            className="relative w-full h-full flex items-center gap-1"
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
        >
            <div className={cn('flex-1 overflow-hidden', !isExpanded && 'text-ellipsis whitespace-nowrap')}>
                {value}
            </div>
            {isHovered && !isExpanded && !hasManualWidth && (
                <LemonButton
                    className="rotate-90 shrink-0"
                    size="xsmall"
                    icon={<IconExpand />}
                    onClick={(e) => {
                        e.stopPropagation()
                        onToggleExpand()
                    }}
                    tooltip={`Expand ${columnName} column`}
                />
            )}
        </div>
    )
}

interface RowDetailsModalProps {
    isOpen: boolean
    onClose: () => void
    row: Record<string, any> | null
    columns: string[]
}

function RowDetailsModal({ isOpen, onClose, row, columns }: RowDetailsModalProps): JSX.Element {
    if (!row) {
        return <></>
    }

    const tableData = columns.map((column) => ({
        column,
        value:
            row[column] === null ? (
                <span className="text-muted">null</span>
            ) : typeof row[column] === 'object' ? (
                <pre className="whitespace-pre-wrap break-all m-0 font-mono">
                    {JSON.stringify(row[column], null, 2)}
                </pre>
            ) : (
                <span className="whitespace-pre-wrap break-all font-mono">{String(row[column])}</span>
            ),
    }))

    return (
        <LemonModal title="Row Details" isOpen={isOpen} onClose={onClose} width={800}>
            <div className="max-h-[70vh] overflow-y-auto px-2">
                <LemonTable
                    dataSource={tableData}
                    columns={[
                        {
                            title: 'Column',
                            dataIndex: 'column',
                            className: 'font-semibold max-w-xs',
                        },
                        {
                            title: 'Value',
                            dataIndex: 'value',
                            className: 'px-4',
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

    const { sourceQuery, exportContext, editorKey, metadataLoading } = useValues(multitabEditorLogic)
    const { saveAsInsight, setSourceQuery } = useActions(multitabEditorLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { response, responseLoading, responseError, queryId, pollResponse } = useValues(dataNodeLogic)
    const { visualizationType, queryCancelled } = useValues(dataVisualizationLogic)
    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const vizKey = useMemo(() => `SQLEditorScene`, [])

    const columns = useMemo(() => {
        const types = response?.types

        return (
            response?.columns?.map((column: string, index: number) => {
                const type = types?.[index]?.[1]

                const maxContentLength = Math.max(
                    column.length,
                    ...response.results.map((row: any[]) => {
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

                // Hack to get bools to render in the data grid
                if (type && type.indexOf('Bool') !== -1) {
                    return {
                        key: column,
                        name: column,
                        resizable: true,
                        width: finalWidth,
                        renderCell: (props: any) => {
                            if (props.row[column] === null) {
                                return null
                            }
                            return props.row[column].toString()
                        },
                    }
                }

                const baseColumn = {
                    key: column,
                    name: column,
                    resizable: true,
                    width: finalWidth,
                }

                return {
                    ...baseColumn,
                    renderCell: (props: any) => props.row[column],
                }
            }) ?? []
        )
    }, [response])

    const rows = useMemo(() => {
        if (!response?.results) {
            return []
        }
        return response?.results?.map((row: any[], index: number) => {
            const rowObject: Record<string, any> = { __index: index }
            response.columns.forEach((column: string, i: number) => {
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

    const [selectedRow, setSelectedRow] = useState<Record<string, any> | null>(null)

    const handleRowClick = useCallback((args: CellClickArgs<any, any>) => {
        setSelectedRow(args.row)
    }, [])

    return (
        <div className="flex flex-col w-full flex-1 bg-primary">
            <div className="flex flex-row justify-between align-center py-2 px-4 w-full h-[55px]">
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(tab) => setActiveTab(tab as OutputTab)}
                    tabs={[
                        {
                            key: OutputTab.Results,
                            label: 'Results',
                        },
                        {
                            key: OutputTab.Visualization,
                            label: 'Visualization',
                        },
                        ...(featureFlags[FEATURE_FLAGS.DATA_MODELING]
                            ? [
                                  {
                                      key: OutputTab.Info,
                                      label: (
                                          <span className="flex flex-row items-center gap-2">
                                              Info {metadataLoading ? <Spinner /> : null}
                                          </span>
                                      ),
                                  },
                                  {
                                      key: OutputTab.Lineage,
                                      label: (
                                          <span className="flex flex-row items-center gap-2">
                                              Lineage {metadataLoading ? <Spinner /> : null}
                                          </span>
                                      ),
                                  },
                              ]
                            : []),
                    ]}
                />
                <div className="flex gap-2">
                    {activeTab === OutputTab.Results && exportContext && (
                        <ExportButton
                            disabledReason={
                                visualizationType != ChartDisplayType.ActionsTable &&
                                'Only table results are exportable'
                            }
                            type="secondary"
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
                    )}
                    {activeTab === OutputTab.Visualization && (
                        <>
                            <div className="flex justify-between flex-wrap">
                                <div className="flex items-center" />
                                <div className="flex items-center">
                                    <div className="flex gap-2 items-center flex-wrap">
                                        <TableDisplay />

                                        <LemonButton
                                            type="secondary"
                                            icon={<IconGear />}
                                            onClick={() => toggleChartSettingsPanel()}
                                            tooltip="Visualization settings"
                                        />

                                        <LemonButton type="primary" onClick={() => saveAsInsight()}>
                                            Create insight
                                        </LemonButton>
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                </div>
            </div>
            <div className="flex flex-1 relative bg-dark">
                <BindLogic logic={lineageTabLogic} props={{ codeEditorKey: editorKey }}>
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
                        onRowClick={handleRowClick}
                    />
                </BindLogic>
            </div>
            <div className="flex justify-between px-2 border-t">
                <div>{response ? <LoadPreviewText /> : <></>}</div>
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
                    <div className={cn('w-full h-full flex-1 overflow-auto')}>{component}</div>
                </div>
            </div>
        </div>
    )
}

const ErrorState = ({ responseError, sourceQuery, queryCancelled, response }: any): JSX.Element | null => {
    return (
        <div className={cn('flex-1 absolute top-0 left-0 right-0 bottom-0 overflow-scroll')}>
            <InsightErrorState
                query={sourceQuery}
                excludeDetail
                title={
                    queryCancelled
                        ? 'The query was cancelled'
                        : response && 'error' in response
                        ? response.error
                        : responseError
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
    setSourceQuery,
    exportContext,
    saveAsInsight,
    queryId,
    pollResponse,
    editorKey,
    onRowClick,
}: any): JSX.Element | null => {
    if (activeTab === OutputTab.Results) {
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

        return responseLoading ? (
            <div className="flex flex-1 p-2 w-full justify-center items-center">
                <StatelessInsightLoadingState queryId={queryId} pollResponse={pollResponse} />
            </div>
        ) : !response ? (
            <div className="flex flex-1 justify-center items-center">
                <span className="text-secondary mt-3">Query results will appear here</span>
            </div>
        ) : (
            <TabScroller>
                <DataGrid
                    className={isDarkModeOn ? 'rdg-dark h-full' : 'rdg-light h-full'}
                    columns={columns}
                    rows={rows}
                    onCellClick={onRowClick}
                />
            </TabScroller>
        )
    }

    if (activeTab === OutputTab.Visualization) {
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

        return !response ? (
            <div className="flex flex-1 justify-center items-center">
                <span className="text-secondary mt-3">Query results will be visualized here</span>
            </div>
        ) : (
            <div className="flex-1 absolute top-0 left-0 right-0 bottom-0 px-4 py-1 hide-scrollbar">
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

    if (activeTab === OutputTab.Info) {
        return <InfoTab codeEditorKey={editorKey} />
    }

    if (activeTab === OutputTab.Lineage) {
        return <LineageTab />
    }

    return null
}
