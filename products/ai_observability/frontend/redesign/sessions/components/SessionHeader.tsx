import { LemonSwitch } from '@posthog/lemon-ui'

import type { SessionListItemApi, TracePersonApi, TracePreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { TracePersonCell } from '../../traces/components/TracePersonCell'
import { sessionFacts } from '../sessionFacts'
import { SessionTitle } from './SessionTitle'

export interface SessionHeaderProps {
    item: SessionListItemApi
    title: TraceCellLoad<TracePreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    conversationOnly: boolean
    onConversationOnlyChange: (conversationOnly: boolean) => void
}

export function SessionHeader({
    item,
    title,
    person,
    conversationOnly,
    onConversationOnlyChange,
}: SessionHeaderProps): JSX.Element {
    return (
        <header className="flex flex-col gap-1 border-b border-primary px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <div className="min-w-0 flex-1 text-base font-semibold">
                    <SessionTitle title={title} />
                </div>
                <LemonSwitch
                    checked={conversationOnly}
                    onChange={onConversationOnlyChange}
                    label="Conversation only"
                    size="small"
                    // pinned: autocapture dashboards and tests select the switch by this value
                    data-attr="ai-observability-session-conversation-only"
                />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                <span>{sessionFacts(item).join(' · ')}</span>
                <TracePersonCell person={person.status === 'ready' ? person.value : null} status={person.status} />
            </div>
        </header>
    )
}
