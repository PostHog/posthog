import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AiObservabilityErrorsListOrder, type ErrorListItemApi } from '../../../generated/api.schemas'
import { ChangeTag } from '../../diagnostics/components/ChangeTag'
import { SortHeader } from '../../diagnostics/components/SortHeader'
import { TrendSparkline } from '../../diagnostics/components/TrendSparkline'
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
    firstSeen: CellLoads<ErrorFirstSeen>
    'data-attr': string
}

function Count({ value }: { value: number }): JSX.Element {
    return (
        <span className="tabular-nums" translate="no">
            {humanFriendlyNumber(value)}
        </span>
    )
}

export function errorsTableColumns({
    maxOccurrences,
    order,
    onOrder,
    firstSeen,
    'data-attr': dataAttr,
}: ErrorsTableColumnsOptions): LemonTableColumns<ErrorListItemApi> {
    const sortable = (
        label: string,
        key: AiObservabilityErrorsListOrder
    ): Pick<LemonTableColumn<ErrorListItemApi, undefined>, 'title' | 'key'> => ({
        key,
        title: (
            <SortHeader
                label={label}
                active={order === key}
                onSort={() => onOrder(key)}
                // pinned: autocapture dashboards and tests select the sort headers by this value
                data-attr={`${dataAttr}-order-${key}`}
            />
        ),
    })

    return [
        {
            title: 'Error',
            key: 'message',
            render: (_, { message }) => <ErrorMessageCell message={message} />,
        },
        {
            ...sortable('Occurrences', AiObservabilityErrorsListOrder.Occurrences),
            align: 'right',
            render: (_, { occurrences }) => (
                <div className="flex flex-col items-end gap-1">
                    <Count value={occurrences} />
                    <div className="w-16">
                        <LemonProgress
                            percent={maxOccurrences > 0 ? (occurrences / maxOccurrences) * 100 : 0}
                            bgColor="var(--color-border-primary)"
                            strokeColor="var(--color-text-tertiary)"
                            smoothing={false}
                        />
                    </div>
                </div>
            ),
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
            render: (_, { traces }) => <Count value={traces} />,
        },
        {
            ...sortable('Users', AiObservabilityErrorsListOrder.Users),
            align: 'right',
            render: (_, { users }) => <Count value={users} />,
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
            render: (_, { key }) => <FirstSeenCell load={firstSeen.get(key)} />,
        },
        {
            ...sortable('Last seen', AiObservabilityErrorsListOrder.LastSeen),
            render: (_, { lastSeen }) => <TZLabel time={lastSeen} />,
        },
    ]
}
