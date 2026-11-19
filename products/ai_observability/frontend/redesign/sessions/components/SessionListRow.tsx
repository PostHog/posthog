import clsx from 'clsx'

import { Link } from '@posthog/lemon-ui'

import type { SessionListItemApi, TracePersonApi, TracePreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TracePersonCell } from '../../traces/components/TracePersonCell'
import { sessionFacts } from '../sessionFacts'
import { SessionTitle } from './SessionTitle'

// pinned: autocapture dashboards and tests select the row's link by this value
const SESSION_LINK_DATA_ATTR = 'ai-observability-session-link'

export interface SessionListRowProps {
    item: SessionListItemApi
    title: TraceCellLoad<TracePreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    isOpen: boolean
    /** Where the title links: the list with this session open. */
    href: string
}

export function SessionListRow({ item, title, person, isOpen, href }: SessionListRowProps): JSX.Element {
    return (
        <div
            className={clsx('flex flex-col gap-1 px-3 py-2', isOpen && 'bg-fill-highlight-100')}
            aria-current={isOpen ? 'true' : undefined}
            data-attr="ai-observability-session-row"
        >
            <Link to={href} subtle className="block min-w-0" data-attr={SESSION_LINK_DATA_ATTR}>
                <SessionTitle title={title} className="font-medium" />
            </Link>
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
