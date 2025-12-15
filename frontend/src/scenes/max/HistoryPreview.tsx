import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ConversationStatus, ConversationType } from '~/types'

import { maxLogic } from './maxLogic'
import { formatConversationDate, getSlackThreadUrl } from './utils'

interface HistoryPreviewProps {
    sidePanel?: boolean
}

export function HistoryPreview({ sidePanel = false }: HistoryPreviewProps): JSX.Element | null {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxLogic)
    const { toggleConversationHistory, openConversation } = useActions(maxLogic)

    if (!conversationHistory.length && !conversationHistoryLoading) {
        return null
    }

    return (
        <div className="max-w-120 w-full self-center flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 -mr-2">
                <h3 className="text-sm font-medium text-secondary mb-0">Recent chats</h3>
                <LemonButton
                    size="small"
                    onClick={() => toggleConversationHistory()}
                    tooltip="Open chat history"
                    tooltipPlacement="bottom"
                >
                    View all
                </LemonButton>
            </div>
            {conversationHistoryLoading && !conversationHistory.length ? (
                <>
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                </>
            ) : (
                conversationHistory.slice(0, 3).map((conversation) => (
                    <span className="flex items-center gap-2">
                        <Link
                            key={conversation.id}
                            className="grow text-sm text-primary hover:text-accent-hover active:text-accent-active"
                            to={urls.ai(conversation.id)}
                            onClick={(e) => {
                                if (sidePanel) {
                                    e.preventDefault()
                                    openConversation(conversation.id)
                                }
                            }}
                        >
                            <div className="flex items-center gap-2">
                                <span className="flex-1 line-clamp-1">{conversation.title}</span>
                                {conversation.is_internal && <LemonTag type="muted">Impersonated</LemonTag>}
                                {conversation.type === ConversationType.DeepResearch && (
                                    <LemonTag>Deep research</LemonTag>
                                )}
                            </div>
                        </Link>

                        {conversation.slack_thread_key && (
                            <LemonTag>
                                <Link
                                    to={getSlackThreadUrl(
                                        conversation.slack_thread_key,
                                        conversation.slack_workspace_domain
                                    )}
                                    target="_blank"
                                    className="flex items-center gap-1 text-primary hover:text-accent-hover active:text-accent-active"
                                    onClick={(e) => e.stopPropagation()}
                                    tooltip="This chat was started in Slack"
                                >
                                    Slack thread <IconExternal />
                                </Link>
                            </LemonTag>
                        )}
                        {conversation.status === ConversationStatus.InProgress ? (
                            <Spinner className="h-4 w-4" />
                        ) : (
                            <span className="text-right text-secondary whitespace-nowrap cursor-default">
                                {formatConversationDate(conversation.updated_at)}
                            </span>
                        )}
                    </span>
                ))
            )}
        </div>
    )
}
