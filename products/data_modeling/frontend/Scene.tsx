import { useActions, useValues } from 'kea'

import { IconDirectedGraph, IconList } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { GraphView } from './GraphView'
import { TableView } from './TableView'
import { dataModelingLogic } from './dataModelingLogic'

function ToolBar(): JSX.Element {
    const { viewNodes, searchTerm, viewMode } = useValues(dataModelingLogic)
    const { setSearchTerm, setViewMode } = useActions(dataModelingLogic)
    return (
        <div className="flex gap-2 items-center">
            {(viewNodes.length > 0 || searchTerm) && (
                <LemonInput type="search" placeholder="Search models..." onChange={setSearchTerm} value={searchTerm} />
            )}
            <div className="flex gap-2 ml-auto">
                <LemonSegmentedButton
                    value={viewMode}
                    onChange={(value) => setViewMode(value)}
                    options={[
                        { value: 'graph', icon: <IconDirectedGraph />, tooltip: 'Graph view' },
                        { value: 'list', icon: <IconList />, tooltip: 'List view' },
                    ]}
                    size="small"
                />
            </div>
        </div>
    )
}

export function DataModelingScene(): JSX.Element {
    const { viewMode, nodesLoading } = useValues(dataModelingLogic)

    if (nodesLoading) {
        return (
            <div className="flex items-center justify-center h-[calc(100vh-17rem)]">
                <Spinner className="text-4xl" />
            </div>
        )
    }

    return (
        <div className="space-y-4 h-full">
            <ToolBar />
            {viewMode === 'graph' ? <GraphView /> : <TableView />}
        </div>
    )
}
