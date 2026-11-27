import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { AiObservabilityErrorsListOrder, type ErrorListItemApi } from '../../../generated/api.schemas'
import { ChangeTag } from '../../diagnostics/components/ChangeTag'
import { CountCell } from '../../diagnostics/components/CountCell'
import { sortableColumn } from '../../diagnostics/components/sortableColumn'
import { TrendSparkline } from '../../diagnostics/components/TrendSparkline'
import { VolumeCell } from '../../diagnostics/components/VolumeCell'
import type { CellLoads } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import type { ErrorFirstSeen } from '../errorFirstSeenLogic'
import { isNewError } from '../isNewError'
import { ErrorMessageCell } from './ErrorMessageCell'
import { FirstSeenCell } from './FirstSeenCell'

export interface ErrorsTableColumnsOptions {
    /** The most occurrences of any error in the selection, which every page scales its volume bars against. */
    maxOccurrences: number
    /** The order the list is sorted by, or null before the list knows it. */
    order: AiObservabilityErrorsListOrder | null
    onOrder: (order: AiObservabilityErrorsListOrder) => void
    onOpen: (item: ErrorListItemApi) => void
    firstSeen: CellLoads<ErrorFirstSeen>
    /** The project's timezone, which first seen dates are shown in. */
    timezone: string
    'data-attr': string
}

export function errorsTableColumns({
    maxOccurrences,
    order,
    onOrder,
    onOpen,
    firstSeen,
    timezone,
    'data-attr': dataAttr,
}: ErrorsTableColumnsOptions): LemonTableColumns<ErrorListItemApi> {
    const sortable = sortableColumn<ErrorListItemApi, AiObservabilityErrorsListOrder>({
        order,
        onOrder,
        'data-attr': dataAttr,
    })

    return [
        {
            title: 'Error',
            key: 'message',
            render: (_, item) => <ErrorMessageCell message={item.message} onOpen={() => onOpen(item)} />,
        },
        {
            ...sortable('Occurrences', AiObservabilityErrorsListOrder.Occurrences),
            align: 'right',
            render: (_, { occurrences }) => <VolumeCell value={occurrences} max={maxOccurrences} />,
        },
        {
            ...sortable('Change', AiObservabilityErrorsListOrder.Change),
            render: (_, { key, changeLabel, changeTone }) => (
                <div className="flex flex-wrap items-center gap-1">
                    <TraceCellValue>
                        {changeLabel === null ? null : <ChangeTag label={changeLabel} tone={changeTone} />}
                    </TraceCellValue>
                    {isNewError(firstSeen.get(key)) ? (
                        <LemonTag type="highlight" size="small">
                            New
                        </LemonTag>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Trend',
            key: 'trend',
            render: (_, { series }) => <TrendSparkline series={series} />,
        },
        {
            ...sortable('Traces', AiObservabilityErrorsListOrder.Traces),
            align: 'right',
            render: (_, { traces }) => <CountCell value={traces} />,
        },
        {
            ...sortable('Users', AiObservabilityErrorsListOrder.Users),
            align: 'right',
            render: (_, { users }) => <CountCell value={users} />,
        },
        {
            title: 'Models',
            key: 'models',
            render: (_, { models }) => (
                <TraceCellValue>
                    {models.length === 0 ? null : (
                        <div className="flex max-w-60 flex-wrap gap-1">
                            {models.map((model) => (
                                <LemonTag key={model} size="small" className="max-w-full" title={model}>
                                    <span className="truncate">{model}</span>
                                </LemonTag>
                            ))}
                        </div>
                    )}
                </TraceCellValue>
            ),
        },
        {
            title: 'First seen',
            key: 'first_seen',
            render: (_, { key }) => <FirstSeenCell load={firstSeen.get(key)} timezone={timezone} />,
        },
        {
            ...sortable('Last seen', AiObservabilityErrorsListOrder.LastSeen),
            render: (_, { lastSeen }) => <TZLabel time={lastSeen} />,
        },
    ]
}
