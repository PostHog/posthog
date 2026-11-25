import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { PersonListItemApi } from '../../../generated/api.schemas'
import type { CellLoads } from '../../shared/cellLoads'
import { formatCostUsd } from '../../shared/formatCost'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import { TracePersonCell } from '../../traces/components/TracePersonCell'
import type { PersonFirstSeen } from '../types'
import { PersonFirstSeenCell } from './PersonFirstSeenCell'

export interface PeopleTableColumnsOptions {
    firstSeen: CellLoads<PersonFirstSeen>
}

function CountValue({ count }: { count: number }): JSX.Element {
    return <TraceCellValue>{count > 0 ? humanFriendlyNumber(count) : null}</TraceCellValue>
}

export function peopleTableColumns({ firstSeen }: PeopleTableColumnsOptions): LemonTableColumns<PersonListItemApi> {
    return [
        {
            title: 'Person',
            key: 'person',
            render: (_, item) => <TracePersonCell person={item.person} status="ready" maxWidthClassName="max-w-full" />,
        },
        {
            title: 'Sessions',
            key: 'sessions',
            align: 'right',
            tooltip: "Sessions this person's events belong to. A session with several people counts for each of them.",
            render: (_, { sessionCount }) => <CountValue count={sessionCount} />,
        },
        {
            title: 'Traces',
            key: 'traces',
            align: 'right',
            tooltip: 'Traces with an event from this person. A trace with several people counts for each of them.',
            render: (_, { traceCount }) => <CountValue count={traceCount} />,
        },
        {
            title: 'Cost',
            key: 'cost',
            align: 'right',
            tooltip:
                "The cost of this person's own events. In a trace with several people, each counts only their own events.",
            render: (_, { cost }) => <TraceCellValue>{cost !== null ? formatCostUsd(cost) : null}</TraceCellValue>,
        },
        {
            title: 'First seen',
            key: 'first_seen',
            render: (_, { id }) => {
                const load = firstSeen.get(id)
                return (
                    <PersonFirstSeenCell
                        firstSeen={load?.status === 'ready' ? load.value : null}
                        // The cells are read right after the row lands, so a row with no entry yet is about to load.
                        status={load?.status ?? 'loading'}
                    />
                )
            },
        },
        {
            title: 'Last seen',
            key: 'last_seen',
            render: (_, { lastSeen }) => <ShortTimestamp time={lastSeen} />,
        },
    ]
}
