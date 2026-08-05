import { useActions, useValues } from 'kea'

import { IconDirectedGraph, IconList } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataModelingLogic } from './dataModelingLogic'
import { GraphView } from './modeling/GraphView'
import { TableView } from './modeling/TableView'

function ToolBar(): JSX.Element {
    const { viewNodes, searchTerm, viewMode, dags, selectedDagId } = useValues(dataModelingLogic)
    const { setSearchTerm, setViewMode, setSelectedDagId } = useActions(dataModelingLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const multiDagEnabled = !!featureFlags[FEATURE_FLAGS.DATA_MODELING_MULTI_DAG]

    const dagOptions =
        viewMode === 'graph'
            ? dags.map((d) => ({ value: d.id, label: d.name }))
            : [
                  { value: null as string | null, label: 'All DAGs' },
                  ...dags.map((d) => ({ value: d.id, label: d.name })),
              ]

    return (
        <div className="flex gap-2 items-center">
            {(viewNodes.length > 0 || searchTerm) && (
                <LemonInput type="search" placeholder="Search models..." onChange={setSearchTerm} value={searchTerm} />
            )}
            <div className="flex gap-2 ml-auto items-center">
                {multiDagEnabled && dags.length > 0 && (
                    <LemonSelect
                        value={selectedDagId}
                        onChange={setSelectedDagId}
                        options={dagOptions}
                        className="w-44"
                        truncateText={{ maxWidthClass: 'max-w-28' }}
                        dropdownMatchSelectWidth={false}
                        menu={{ className: 'max-w-60' }}
                        size="small"
                    />
                )}
                <LemonSegmentedButton
                    value={viewMode}
                    onChange={(value) => setViewMode(value)}
                    options={[
                        {
                            value: 'graph',
                            icon: <IconDirectedGraph />,
                            tooltip: 'Graph view',
                        },
                        { value: 'list', icon: <IconList />, tooltip: 'List view' },
                    ]}
                    size="small"
                />
            </div>
        </div>
    )
}

export function DataModelingTab(): JSX.Element {
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
