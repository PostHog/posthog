import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCard,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'

import type {
    AccountEmailThreadApi,
    AccountEmailThreadMessageApi,
    AccountEmailThreadParticipantApi,
    PaginatedAccountEmailThreadMessageListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountEmailThreadsLogic, MESSAGE_PAGE_SIZE, NOT_LOADED, PAGE_SIZE } from './accountEmailThreadsLogic'

const COLLAPSED_PARTICIPANT_COUNT = 3

function EmailThreadsEmptyState({ title, detail }: { title: string; detail: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <BigLeaguesHog className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
        </div>
    )
}

function participantLabel(participant: AccountEmailThreadParticipantApi): string {
    return participant.display_name || participant.email
}

function ParticipantList({ participants }: { participants: readonly AccountEmailThreadParticipantApi[] }): JSX.Element {
    const customerParticipants = participants.filter((participant) => participant.kind === 'customer')
    const shown = customerParticipants.slice(0, COLLAPSED_PARTICIPANT_COUNT)
    const hiddenCount = customerParticipants.length - shown.length

    if (shown.length === 0) {
        return <span className="text-muted">No customer participants</span>
    }

    return (
        <span>
            {shown.map((participant, index) => (
                <span key={participant.email} title={participant.email}>
                    {participantLabel(participant)}
                    {index < shown.length - 1 ? ', ' : ''}
                </span>
            ))}
            {hiddenCount > 0 ? `, +${hiddenCount} more` : null}
        </span>
    )
}

function recipientSummary(message: AccountEmailThreadMessageApi): string {
    const recipients = [...message.to_recipients, ...message.cc_recipients]
    return recipients.map((recipient) => recipient.name || recipient.email).join(', ')
}

function EmailMessage({ message }: { message: AccountEmailThreadMessageApi }): JSX.Element {
    const sender = message.sender.name || message.sender.email
    const recipients = recipientSummary(message)
    return (
        <LemonCard hoverEffect={false} className="p-3 flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col min-w-0">
                    <span className="font-semibold truncate" title={message.sender.email}>
                        {sender}
                    </span>
                    {recipients ? (
                        <span className="text-xs text-secondary truncate" title={recipients}>
                            To: {recipients}
                        </span>
                    ) : null}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    {message.direction === 'inbound' && !message.sender_authenticated ? (
                        <Tooltip title="PostHog couldn't verify this sender's domain. Check the sender before sharing account details.">
                            <LemonTag type="warning">Unverified sender</LemonTag>
                        </Tooltip>
                    ) : null}
                    <LemonTag type={message.direction === 'outbound' ? 'primary' : 'default'}>
                        {message.direction === 'outbound' ? 'Outgoing' : 'Incoming'}
                    </LemonTag>
                    <TZLabel time={message.sent_at} />
                </div>
            </div>
            <div className="whitespace-pre-wrap break-words text-sm">{message.content}</div>
        </LemonCard>
    )
}

function ThreadDetail({ accountId, threadId }: { accountId: string; threadId: string }): JSX.Element {
    const logic = accountEmailThreadsLogic({ accountId })
    const { threadDetails, threadDetailsLoading, threadDetailErrors, threadDetailPages } = useValues(logic)
    const { setThreadDetailPage } = useActions(logic)
    const detail: PaginatedAccountEmailThreadMessageListApi | undefined = threadDetails[threadId]
    const page = threadDetailPages[threadId] ?? 1

    if (threadDetailsLoading[threadId] || (!detail && !threadDetailErrors[threadId])) {
        return <LemonSkeleton className="h-40 w-full" />
    }
    if (threadDetailErrors[threadId]) {
        return (
            <EmailThreadsEmptyState
                title="Couldn't load this email thread"
                detail="Collapse the thread and open it again. If it still doesn't load, refresh the page."
            />
        )
    }
    if (!detail) {
        return <></>
    }
    return (
        <div className="flex flex-col gap-2 py-2" data-attr="account-email-thread-detail">
            {detail.results.map((message) => (
                <EmailMessage key={message.id} message={message} />
            ))}
            <PaginationControl
                pagination={{ controlled: true, pageSize: MESSAGE_PAGE_SIZE }}
                currentPage={page}
                setCurrentPage={(newPage) => setThreadDetailPage(threadId, newPage)}
                pageCount={Math.max(1, Math.ceil(detail.count / MESSAGE_PAGE_SIZE))}
                dataSourcePage={detail.results}
                entryCount={detail.count}
                currentStartIndex={(page - 1) * MESSAGE_PAGE_SIZE}
                currentEndIndex={(page - 1) * MESSAGE_PAGE_SIZE + detail.results.length}
                nouns={['message', 'messages']}
            />
        </div>
    )
}

export function AccountEmailThreadsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountEmailThreadsLogic({ accountId })
    const { threadsResult, threadsResultLoading, page, expandedThreadId } = useValues(logic)
    const { setPage, openThread, closeThread } = useActions(logic)

    const toggleThread = (threadId: string): void => {
        if (threadId === expandedThreadId) {
            closeThread(threadId)
        } else {
            openThread(threadId)
        }
    }

    if (threadsResult === NOT_LOADED || threadsResultLoading) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { threads, count, loadFailed } = threadsResult
    if (loadFailed) {
        return (
            <EmailThreadsEmptyState
                title="Couldn't load email threads"
                detail="Refresh the page to try loading this account's email threads again."
            />
        )
    }
    if (count === 0) {
        return (
            <EmailThreadsEmptyState
                title="No email threads yet"
                detail="Forwarded customer email that matches this account will show up here."
            />
        )
    }

    const columns: LemonTableColumns<AccountEmailThreadApi> = [
        {
            title: 'Thread',
            key: 'subject',
            render: (_, thread) => (
                <LemonButton
                    type="tertiary"
                    fullWidth
                    noPadding
                    className="justify-start text-left"
                    aria-expanded={thread.id === expandedThreadId}
                    onClick={() => toggleThread(thread.id)}
                >
                    <div className="flex flex-col gap-1 py-1 max-w-xl min-w-0">
                        <span className="font-medium line-clamp-1">{thread.subject || 'No subject'}</span>
                        {thread.preview ? (
                            <span className="text-xs text-muted line-clamp-1">{thread.preview}</span>
                        ) : null}
                    </div>
                </LemonButton>
            ),
        },
        {
            title: 'Participants',
            key: 'participants',
            render: (_, thread) => (
                <LemonButton
                    type="tertiary"
                    fullWidth
                    noPadding
                    className="justify-start text-left"
                    aria-expanded={thread.id === expandedThreadId}
                    onClick={() => toggleThread(thread.id)}
                >
                    <ParticipantList participants={thread.participants} />
                </LemonButton>
            ),
        },
        {
            title: 'Messages',
            key: 'message_count',
            align: 'right',
            render: (_, thread) => thread.message_count,
        },
        {
            title: 'Last activity',
            key: 'last_message_at',
            width: 150,
            render: (_, thread) =>
                thread.last_message_at ? (
                    <TZLabel time={thread.last_message_at} />
                ) : (
                    <span className="text-muted">Not available</span>
                ),
        },
    ]

    return (
        <LemonTable<AccountEmailThreadApi>
            data-attr="account-email-threads-table"
            size="small"
            embedded
            dataSource={threads ?? []}
            columns={columns}
            rowKey="id"
            tableLayout="fixed"
            pagination={{
                controlled: true,
                pageSize: PAGE_SIZE,
                currentPage: page,
                useUrl: false,
                entryCount: count,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            expandable={{
                expandedRowRender: (thread) => <ThreadDetail accountId={accountId} threadId={thread.id} />,
                isRowExpanded: (thread) => thread.id === expandedThreadId,
                onRowExpand: (thread) => openThread(thread.id),
                onRowCollapse: (thread) => closeThread(thread.id),
                rowExpandable: () => true,
                showRowExpansionToggle: false,
            }}
            emptyState="No email threads on this page."
        />
    )
}
