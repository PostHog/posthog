import { Link } from '@posthog/lemon-ui'

import type { SessionListItemApi, SessionPreviewApi } from '../../../generated/api.schemas'
import { SessionTitle } from '../../sessions/components/SessionTitle'
import { sessionFacts } from '../../sessions/sessionFacts'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'

const TITLE_FAILED = "Couldn't load this session's title."

export interface RecentSessionRowProps {
    session: SessionListItemApi
    title: TraceCellLoad<SessionPreviewApi>
    href: string
}

export function RecentSessionRow({ session, title, href }: RecentSessionRowProps): JSX.Element {
    return (
        <li>
            <Link
                to={href}
                subtle
                className="flex w-full min-w-0 flex-col gap-0.5 rounded border border-primary px-2 py-1.5 hover:bg-fill-highlight-100"
                // pinned: autocapture dashboards select a recent session by this value
                data-attr="ai-observability-person-drawer-session"
            >
                <SessionTitle title={title} failedMessage={TITLE_FAILED} className="font-semibold" />
                <span className="flex w-full items-center gap-2 text-xs text-secondary">
                    <span>{sessionFacts(session).join(' · ')}</span>
                    <span className="ml-auto shrink-0">
                        <ShortTimestamp time={session.lastSeen} />
                    </span>
                </span>
            </Link>
        </li>
    )
}
