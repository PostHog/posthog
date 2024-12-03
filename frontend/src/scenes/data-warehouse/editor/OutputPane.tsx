import 'react-data-grid/lib/styles.css'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { useMemo } from 'react'
import DataGrid from 'react-data-grid'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { Table } from '~/queries/nodes/DataVisualization/Components/Table'
import { TableDisplay } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { VariablesForInsight } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { DataTableVisualizationProps } from '~/queries/nodes/DataVisualization/DataVisualization'
import {
    dataVisualizationLogic,
    DataVisualizationLogicProps,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema'
import { ChartDisplayType, ExporterFormat, ItemMode } from '~/types'

import { DATAWAREHOUSE_EDITOR_ITEM_ID } from '../external/dataWarehouseExternalSceneLogic'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { multitabEditorLogic } from './multitabEditorLogic'
import { outputPaneLogic, OutputTab } from './outputPaneLogic'

interface OutputPaneProps {
    onSave: () => void
    saveDisabledReason?: string
    onQueryInputChange: () => void
    logicKey: string
    query: string
}

export function OutputPane({
    onQueryInputChange,
    onSave,
    saveDisabledReason,
    logicKey,
    query,
}: OutputPaneProps): JSX.Element {
    const { activeTab } = useValues(outputPaneLogic)
    const { setActiveTab } = useActions(outputPaneLogic)

    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const { editingView, queryInput } = useValues(
        multitabEditorLogic({
            key: codeEditorKey,
        })
    )
    const { isDarkModeOn } = useValues(themeLogic)
    const { response, responseLoading } = useValues(
        dataNodeLogic({
            key: logicKey,
            query: {
                kind: NodeKind.HogQLQuery,
                query,
            },
            doNotLoad: !query,
        })
    )
    const { dataWarehouseSavedQueriesLoading } = useValues(dataWarehouseViewsLogic)
    const { updateDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
            cachedInsight: null,
            doNotLoad: true,
        })
    )
    const { setQuery } = useActions(
        insightDataLogic({
            ...insightProps,
        })
    )

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

    const Content = (): JSX.Element | null => {
        if (activeTab === OutputTab.Results) {
            return responseLoading ? (
                <Spinner className="text-3xl" />
            ) : !response ? (
                <span className="text-muted mt-3">Query results will appear here</span>
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
            return !response ? (
                <div className="flex-1 absolute top-0 left-0 right-0 bottom-0 px-4 py-1 hide-scrollbar">
                    <span className="text-muted mt-3">Query results will visualized here</span>
                </div>
            ) : (
                <div className="flex-1 absolute top-0 left-0 right-0 bottom-0 px-4 py-1 hide-scrollbar">
                    <DataTableVisualizationContent
                        activeTab={activeTab}
                        query={{
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query,
                            },
                        }}
                        setQuery={setQuery}
                    />
                </div>
            )
        }

        return null
    }

    return (
        <div className="flex flex-col w-full flex-1 bg-bg-3000">
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
                    ]}
                />
                <div className="flex gap-4">
                    {editingView ? (
                        <>
                            <LemonButton
                                loading={dataWarehouseSavedQueriesLoading}
                                type="secondary"
                                onClick={() =>
                                    updateDataWarehouseSavedQuery({
                                        id: editingView.id,
                                        query: {
                                            kind: NodeKind.HogQLQuery,
                                            query: queryInput,
                                        },
                                        types: response?.types ?? [],
                                    })
                                }
                            >
                                Update view
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton type="secondary" onClick={() => onSave()} disabledReason={saveDisabledReason}>
                            Save as view
                        </LemonButton>
                    )}
                    <LemonButton loading={responseLoading} type="primary" onClick={() => onQueryInputChange()}>
                        <span className="mr-1">Run</span>
                        <KeyboardShortcut command enter />
                    </LemonButton>
                </div>
            </div>
            <div className="flex flex-1 relative bg-dark justify-center items-center">
                <Content />
            </div>
        </div>
    )
}

function DataTableVisualizationContent({
    query,
    setQuery,
    activeTab,
}: {
    query: DataVisualizationNode
    setQuery: (query: DataVisualizationNode) => void
    activeTab: OutputTab
}): JSX.Element {
    const vizKey = `SQLEditorScene.${activeTab}`
    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: vizKey,
        query,
        dashboardId: undefined,
        dataNodeCollectionId: vizKey,
        insightMode: ItemMode.Edit,
        loadPriority: undefined,
        setQuery,
        cachedResults: undefined,
        variablesOverride: undefined,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: vizKey,
        variablesOverride: undefined,
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <BindLogic logic={variablesLogic} props={{ key: dataVisualizationLogicProps.key, readOnly: false }}>
                        <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <InternalDataTableVisualization
                                uniqueKey={vizKey}
                                query={query}
                                setQuery={setQuery}
                                context={{}}
                                cachedResults={undefined}
                            />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function InternalDataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const logic = insightLogic({
        dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
        cachedInsight: null,
    })
    const { saveAs } = useActions(logic)

    const {
        query,
        visualizationType,
        showEditingUI,
        showResultControls,
        response,
        responseLoading,
        responseError,
        queryCancelled,
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
                    <div className={clsx('w-full h-full flex-1 overflow-auto')}>
                        {visualizationType !== ChartDisplayType.ActionsTable && responseError ? (
                            <div
                                className={clsx('rounded bg-bg-light relative flex flex-1 flex-col p-2', {
                                    border: showEditingUI,
                                })}
                            >
                                <InsightErrorState
                                    query={props.query}
                                    excludeDetail
                                    title={
                                        queryCancelled
                                            ? 'The query was cancelled'
                                            : response && 'error' in response
                                            ? (response as any).error
                                            : responseError
                                    }
                                />
                            </div>
                        ) : (
                            component
                        )}
                    </div>
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

                                    {props.exportContext && (
                                        <ExportButton
                                            disabledReason={
                                                visualizationType != ChartDisplayType.ActionsTable &&
                                                'Only table results are exportable'
                                            }
                                            type="secondary"
                                            items={[
                                                {
                                                    export_format: ExporterFormat.CSV,
                                                    export_context: props.exportContext,
                                                },
                                                {
                                                    export_format: ExporterFormat.XLSX,
                                                    export_context: props.exportContext,
                                                },
                                            ]}
                                        />
                                    )}

                                    <LemonButton type="primary" onClick={() => saveAs(true, false)}>
                                        Create insight
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    </>
                )}

                <VariablesForInsight />
            </div>
        </div>
    )
}
