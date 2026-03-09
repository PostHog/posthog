import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import { aiConversationsPanelLogic, type AIConversationsPanelLogicProps } from './aiConversationsPanelLogic'

interface AIConversationsPanelProps {
    personId: string
    ticketCreatedAt: string
}

function formatRelativeToTicket(sessionTimestamp: string, ticketCreatedAt: string): string {
    const sessionMs = new Date(sessionTimestamp).getTime()
    const ticketMs = new Date(ticketCreatedAt).getTime()
    const diffMs = Math.abs(sessionMs - ticketMs)
    const duration = humanFriendlyDuration(diffMs / 1000)
    if (sessionMs < ticketMs) {
        return `${duration} before ticket created`
    }
    return `${duration} after ticket created`
}

export function AIConversationsPanel({ personId, ticketCreatedAt }: AIConversationsPanelProps): JSX.Element {
    const logicProps: AIConversationsPanelLogicProps = { personId, ticketCreatedAt }
    const { sessions, sessionsLoading, totalCount } = useValues(aiConversationsPanelLogic(logicProps))
    const { loadSessions } = useActions(aiConversationsPanelLogic(logicProps))

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'ai-conversations',
                    header: (
                        <>
                            AI conversations
                            {totalCount > 0 && <span className="text-muted-alt font-normal ml-1">({totalCount})</span>}
                        </>
                    ),
                    content: (
                        <div className="space-y-2">
                            {sessionsLoading ? (
                                <div className="space-y-2">
                                    <LemonSkeleton className="h-4 w-3/4" />
                                    <LemonSkeleton className="h-4 w-1/2" />
                                </div>
                            ) : sessions.length === 0 ? (
                                <div className="text-muted-alt text-xs">No AI conversations found for this person</div>
                            ) : (
                                <>
                                    <div className="space-y-1">
                                        {sessions.map((session) => (
                                            <Link
                                                key={session.sessionId}
                                                to={urls.llmAnalyticsSession(session.sessionId)}
                                                target="_blank"
                                                className="flex items-center gap-1 text-xs py-1 hover:bg-accent-3000 rounded px-1 -mx-1"
                                            >
                                                <span className="flex-1">
                                                    {formatRelativeToTicket(session.createdAt, ticketCreatedAt)}
                                                </span>
                                                <IconExternal className="text-muted-alt shrink-0" />
                                            </Link>
                                        ))}
                                    </div>
                                    {totalCount > sessions.length && (
                                        <div className="text-xs text-muted-alt pt-1">
                                            Showing {sessions.length} of {totalCount}.{' '}
                                            <LemonButton
                                                type="tertiary"
                                                size="xsmall"
                                                to={urls.llmAnalyticsSessions()}
                                                targetBlank
                                            >
                                                View all
                                            </LemonButton>
                                        </div>
                                    )}
                                </>
                            )}
                            {!sessionsLoading && sessions.length === 0 && (
                                <div className="flex justify-end pt-1">
                                    <LemonButton type="tertiary" size="xsmall" onClick={loadSessions}>
                                        Retry
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
