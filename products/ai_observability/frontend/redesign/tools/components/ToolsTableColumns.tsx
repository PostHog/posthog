import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { percentage } from 'lib/utils/numbers'

import { AiObservabilityToolsListOrder, type ToolListItemApi } from '../../../generated/api.schemas'
import { ChangeTag } from '../../diagnostics/components/ChangeTag'
import { CountCell } from '../../diagnostics/components/CountCell'
import { sortableColumn } from '../../diagnostics/components/sortableColumn'
import { TrendSparkline } from '../../diagnostics/components/TrendSparkline'
import { VolumeCell } from '../../diagnostics/components/VolumeCell'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import { FailureRateCell } from './FailureRateCell'

export interface ToolsTableColumnsOptions {
    /** The most calls of any tool in the selection, which every page scales its volume bars against. */
    maxCalls: number
    /** The order the list is sorted by, or null before the list knows it. */
    order: AiObservabilityToolsListOrder | null
    onOrder: (order: AiObservabilityToolsListOrder) => void
    'data-attr': string
}

export function toolsTableColumns({
    maxCalls,
    order,
    onOrder,
    'data-attr': dataAttr,
}: ToolsTableColumnsOptions): LemonTableColumns<ToolListItemApi> {
    const sortable = sortableColumn<ToolListItemApi, AiObservabilityToolsListOrder>({
        order,
        onOrder,
        'data-attr': dataAttr,
    })

    return [
        {
            title: 'Tool',
            key: 'name',
            render: (_, { name }) => (
                <span className="ph-sensitive ph-mask block min-w-40 max-w-80 break-all font-mono text-xs">{name}</span>
            ),
        },
        {
            ...sortable('Calls', AiObservabilityToolsListOrder.Calls),
            align: 'right',
            render: (_, { calls }) => <VolumeCell value={calls} max={maxCalls} />,
        },
        {
            ...sortable('Change', AiObservabilityToolsListOrder.Change),
            render: (_, { changeLabel, changeTone }) => (
                <TraceCellValue>
                    {changeLabel === null ? null : <ChangeTag label={changeLabel} tone={changeTone} />}
                </TraceCellValue>
            ),
        },
        {
            title: 'Trend',
            key: 'trend',
            render: (_, { series }) => <TrendSparkline series={series} />,
        },
        {
            ...sortable('Traces', AiObservabilityToolsListOrder.Traces),
            align: 'right',
            render: (_, { traces }) => <CountCell value={traces} />,
        },
        {
            ...sortable('Failure rate', AiObservabilityToolsListOrder.FailureRate),
            align: 'right',
            render: (_, item) => <FailureRateCell tool={item} />,
        },
        {
            title: 'Failures',
            key: 'failures',
            align: 'right',
            render: (_, { failures }) => (
                <TraceCellValue>{failures === null ? null : <CountCell value={failures} />}</TraceCellValue>
            ),
        },
        {
            title: 'Only tool',
            key: 'only_tool',
            align: 'right',
            tooltip: 'The share of calls made by a generation that called no other tool.',
            render: (_, { onlyToolShare }) => (
                <span className="tabular-nums" translate="no">
                    {percentage(onlyToolShare, 1)}
                </span>
            ),
        },
        {
            ...sortable('Last seen', AiObservabilityToolsListOrder.LastSeen),
            render: (_, { lastSeen }) => <TZLabel time={lastSeen} />,
        },
    ]
}
