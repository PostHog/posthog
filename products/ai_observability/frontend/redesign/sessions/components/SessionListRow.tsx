import clsx from 'clsx'

import type { SessionListItemApi, TracePersonApi, SessionPreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TracePersonCell } from '../../traces/components/TracePersonCell'
import { sessionFacts } from '../sessionFacts'
import { SessionTitle } from './SessionTitle'

export interface SessionListRowProps {
    item: SessionListItemApi
    title: TraceCellLoad<SessionPreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    isOpen: boolean
}

export function SessionListRow({ item, title, person, isOpen }: SessionListRowProps): JSX.Element {
    return (
        <div
            className={clsx('flex w-0 min-w-full flex-col gap-1 px-3 py-2', isOpen && 'bg-fill-highlight-100')}
            aria-current={isOpen ? 'true' : undefined}
            data-attr="ai-observability-session-row"
        >
            <SessionTitle title={title} className="font-medium" />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                <TracePersonCell person={person.status === 'ready' ? person.value : null} status={person.status} />
                <span>{sessionFacts(item).join(' · ')}</span>
                <span className="ml-auto">
                    <ShortTimestamp time={item.lastSeen} />
                </span>
            </div>
        </div>
    )
}
