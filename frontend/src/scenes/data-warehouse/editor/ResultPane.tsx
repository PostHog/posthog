import 'react-data-grid/lib/styles.css'

import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useMemo } from 'react'
import DataGrid from 'react-data-grid'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
enum ResultsTab {
    Results = 'results',
    Visualization = 'visualization',
}

interface ResultPaneProps {
    onSave: () => void
    saveDisabledReason?: string
    onQueryInputChange: () => void
}

export function ResultPane({ onQueryInputChange, onSave, saveDisabledReason }: ResultPaneProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { response, responseLoading } = useValues(dataNodeLogic)

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
                    <LemonButton type="secondary" onClick={() => onSave()} disabledReason={saveDisabledReason}>
                        Save
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => onQueryInputChange()}>
                        Run
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
                        <DataGrid className={isDarkModeOn ? 'rdg-dark' : 'rdg-light'} columns={columns} rows={rows} />
                    </div>
                )}
            </div>
        </div>
    )
}
