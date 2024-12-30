import 'react-data-grid/lib/styles.css'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMemo } from 'react'
import DataGrid from 'react-data-grid'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { Table } from '~/queries/nodes/DataVisualization/Components/Table'
import { TableDisplay } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import { AddVariableButton } from '~/queries/nodes/DataVisualization/Components/Variables/AddVariableButton'
import { VariablesForInsight } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { DataTableVisualizationProps } from '~/queries/nodes/DataVisualization/DataVisualization'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { HogQLQueryResponse } from '~/queries/schema'
import { ChartDisplayType, ExporterFormat } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { outputPaneLogic, OutputTab } from './outputPaneLogic'
import { InfoTab } from './OutputPaneTabs/InfoTab'

export function OutputPane(): JSX.Element {
    const { activeTab } = useValues(outputPaneLogic)
    const { setActiveTab } = useActions(outputPaneLogic)
    const { variablesForInsight } = useValues(variablesLogic)

    const { editingView, sourceQuery, exportContext, isValidView, error, editorKey } = useValues(multitabEditorLogic)
    const { saveAsInsight, saveAsView, setSourceQuery, runQuery } = useActions(multitabEditorLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { response, responseLoading, responseError, queryId, pollResponse } = useValues(dataNodeLogic)
    const { dataWarehouseSavedQueriesLoading } = useValues(dataWarehouseViewsLogic)
    const { updateDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)
    const { visualizationType, queryCancelled } = useValues(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const vizKey = useMemo(() => `SQLEditorScene`, [])

    const columns = useMemo(() => {
        return (
            response?.columns?.map((column: string) => ({
                key: column,
                name: column,
                resizable: true,
            })) ?? []
        )
    }, [response])

    const rows = useMemo(() => {
        if (!response?.results) {
            return []
        }
        return response?.results?.map((row: any[]) => {
            const rowObject: Record<string, any> = {}
            response.columns.forEach((column: string, i: number) => {
                rowObject[column] = row[i]
            })
            return rowObject
        })
    }, [response])

    return (
        <div className="flex flex-col w-full flex-1 bg-bg-3000">
            {variablesForInsight.length > 0 && (
                <div className="py-2 px-4">
                    <VariablesForInsight />
                </div>
            )}
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
                                      label: 'Info',
                                  },
                              ]
                            : []),
                    ]}
                />
                <div className="flex gap-4">
                    <AddVariableButton />

                    {exportContext && (
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

                    {editingView ? (
                        <>
                            <LemonButton
                                loading={dataWarehouseSavedQueriesLoading}
                                type="secondary"
                                onClick={() =>
                                    updateDataWarehouseSavedQuery({
                                        id: editingView.id,
                                        query: sourceQuery.source,
                                        types: response?.types ?? [],
                                    })
                                }
                            >
                                Update view
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton
                            type="secondary"
                            onClick={() => saveAsView()}
                            disabledReason={isValidView ? '' : 'Some fields may need an alias'}
                        >
                            Save as view
                        </LemonButton>
                    )}
                    <LemonButton
                        disabledReason={error ? error : ''}
                        loading={responseLoading}
                        type="primary"
                        onClick={() => runQuery()}
                    >
                        <span className="mr-1">Run</span>
                        <KeyboardShortcut command enter />
                    </LemonButton>
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
                />
            </div>
            <div className="flex justify-end pr-2 border-t">
                <ElapsedTime />
            </div>
        </div>
    )
}

function InternalDataTableVisualization(
    props: DataTableVisualizationProps & { onSaveInsight: () => void }
): JSX.Element {
    const {
        query,
        visualizationType,
        showEditingUI,
        showResultControls,
        response,
        responseLoading,
        isChartSettingsPanelOpen,
    } = useValues(dataVisualizationLogic)

    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)

    let component: JSX.Element | null = null

    // TODO(@Gilbert09): Better loading support for all components - e.g. using the `loading` param of `Table`
    if (!showEditingUI && (!response || responseLoading)) {
        component = (
            <div className="flex flex-col flex-1 justify-center items-center border rounded bg-bg-light">
                <Animation type={AnimationType.LaptopHog} />
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
        <div className="h-full hide-scrollbar flex flex-1 gap-2">
            <div className="relative w-full flex flex-col gap-4 flex-1">
                <div className="flex flex-1 flex-row gap-4 overflow-scroll hide-scrollbar">
                    {isChartSettingsPanelOpen && (
                        <div>
                            <SideBar />
                        </div>
                    )}
                    <div className={clsx('w-full h-full flex-1 overflow-auto')}>{component}</div>
                </div>
                {showResultControls && (
                    <>
                        <div className="flex gap-4 justify-between flex-wrap px-px py-2">
                            <div className="flex gap-4 items-center" />
                            <div className="flex gap-4 items-center">
                                <div className="flex gap-4 items-center flex-wrap">
                                    <TableDisplay />

                                    <LemonButton
                                        icon={<IconGear />}
                                        type={isChartSettingsPanelOpen ? 'primary' : 'secondary'}
                                        onClick={() => toggleChartSettingsPanel()}
                                        tooltip="Visualization settings"
                                    />

                                    <LemonButton type="primary" onClick={() => props.onSaveInsight()}>
                                        Create insight
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

const ErrorState = ({ responseError, sourceQuery, queryCancelled, response }: any): JSX.Element | null => {
    return (
        <div className={clsx('flex-1 absolute top-0 left-0 right-0 bottom-0 overflow-scroll')}>
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
            <StatelessInsightLoadingState queryId={queryId} pollResponse={pollResponse} />
        ) : !response ? (
            <div className="flex flex-1 justify-center items-center">
                <span className="text-muted mt-3">Query results will appear here</span>
            </div>
        ) : (
            <div className="flex-1 absolute top-0 left-0 right-0 bottom-0">
                <DataGrid
                    className={isDarkModeOn ? 'rdg-dark h-full' : 'rdg-light h-full'}
                    columns={columns}
                    rows={rows}
                />
            </div>
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
                <span className="text-muted mt-3">Query results will be visualized here</span>
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
        return (
            <div className="flex flex-1 relative bg-dark">
                <InfoTab codeEditorKey={editorKey} />
            </div>
        )
    }

    return null
}
