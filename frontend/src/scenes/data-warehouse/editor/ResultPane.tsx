import 'react-data-grid/lib/styles.css'

import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'
import DataGrid from 'react-data-grid'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { multitabEditorLogic } from './multitabEditorLogic'

enum ResultsTab {
    Results = 'results',
    Visualization = 'visualization',
}

interface ResultPaneProps {
    onSave: () => void
    saveDisabledReason?: string
    onQueryInputChange: () => void
    logicKey: string
    query: string
}

export function ResultPane({
    onQueryInputChange,
    onSave,
    saveDisabledReason,
    logicKey,
    query,
}: ResultPaneProps): JSX.Element {
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
            <div className="flex flex-row justify-between align-center py-2 px-4 w-full h-[55px]">
                <LemonTabs
                    activeKey={ResultsTab.Results}
                    onChange={() => {}}
                    tabs={[
                        {
                            key: ResultsTab.Results,
                            label: 'Results',
                        },
                    ]}
                />
                <div className="flex gap-1">
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
                                Update
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton type="secondary" onClick={() => onSave()} disabledReason={saveDisabledReason}>
                            Save
                        </LemonButton>
                    )}
                    <LemonButton loading={responseLoading} type="primary" onClick={() => onQueryInputChange()}>
                        <span className="mr-1">Run</span>
                        <KeyboardShortcut command enter />
                    </LemonButton>
                </div>
            </div>
            <div className="flex flex-1 relative bg-dark justify-center items-center">
                {responseLoading ? (
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
                )}
            </div>
        </div>
    )
}
