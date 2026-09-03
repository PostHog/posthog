import { useActions, useValues } from 'kea'

import { IconChevronDown, IconLock, IconSupport } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCheckbox,
    LemonDropdown,
    LemonInput,
    LemonMenu,
    LemonMenuItems,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    Link,
    ProfilePicture,
    Tooltip,
} from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import gmailIcon from 'public/services/gmail.png'

import type {
    AccountEmailThreadMessageApi,
    AccountSupportTicketMessageApi,
    ConversationMessageSummaryApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    AccountConversation,
    accountConversationsLogic,
    ConversationSource,
    NOT_LOADED,
} from './accountConversationsLogic'
import { accountEmailThreadsLogic, MESSAGE_PAGE_SIZE } from './accountEmailThreadsLogic'
import { periodLabel } from './AccountSummariesExpansion'
import { AccountSummaryCadencePicker } from './AccountSummaryCadencePicker'

const SOURCE_OPTIONS: { key: ConversationSource; label: string }[] = [
    { key: 'email', label: 'Gmail' },
    { key: 'support', label: 'Support' },
    { key: 'slack', label: 'Slack' },
]
const VISIBLE_PARTICIPANT_COUNT = 3

function EmptyState({ title, detail }: { title: string; detail: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <BigLeaguesHog className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
        </div>
    )
}

function SourceIcon({ source }: { source: ConversationSource }): JSX.Element {
    const label = SOURCE_OPTIONS.find((option) => option.key === source)?.label ?? source
    return (
        <Tooltip title={label}>
            <span className="inline-flex shrink-0 text-lg" aria-label={label}>
                {source === 'email' ? (
                    <img src={gmailIcon} alt="" className="size-4 object-contain" />
                ) : source === 'support' ? (
                    <IconSupport />
                ) : (
                    <IconSlack />
                )}
            </span>
        </Tooltip>
    )
}

function SourceFilter({
    sources,
    onChange,
}: {
    sources: ConversationSource[]
    onChange: (sources: ConversationSource[]) => void
}): JSX.Element {
    const allSelected = sources.length === SOURCE_OPTIONS.length
    const label = allSelected
        ? 'All sources'
        : sources.length === 1
          ? (SOURCE_OPTIONS.find((option) => option.key === sources[0])?.label ?? sources[0])
          : `${sources.length} sources`
    const items: LemonMenuItems = [
        {
            title: 'Sources',
            items: SOURCE_OPTIONS.map((option) => ({
                icon: <LemonCheckbox checked={sources.includes(option.key)} className="pointer-events-none" />,
                label: option.label,
                onClick: () =>
                    onChange(
                        sources.includes(option.key)
                            ? sources.filter((source) => source !== option.key)
                            : SOURCE_OPTIONS.map(({ key }) => key).filter(
                                  (source) => sources.includes(source) || source === option.key
                              )
                    ),
            })),
        },
    ]

    return (
        <LemonMenu items={items} closeOnClickInside={false} placement="bottom-start">
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                className="shrink-0"
                aria-label={allSelected ? 'All sources selected' : `${sources.length} sources selected`}
                data-attr="account-conversations-source-filter"
            >
                {label}
            </LemonButton>
        </LemonMenu>
    )
}

function ActivityTimestamp({ time }: { time: string }): JSX.Element {
    return (
        <span className="self-start text-xs text-muted">
            <TZLabel time={time} />
        </span>
    )
}

interface ConversationParticipant {
    key: string
    name: string
    email?: string
    personId?: string | null
}

function ParticipantList({ participants }: { participants: ConversationParticipant[] }): JSX.Element {
    const visibleParticipants = participants.slice(0, VISIBLE_PARTICIPANT_COUNT)
    const hiddenParticipants = participants.slice(VISIBLE_PARTICIPANT_COUNT)

    return (
        <span className="flex flex-wrap items-center gap-2">
            {visibleParticipants.map((participant) => (
                <Person
                    key={participant.key}
                    name={participant.name}
                    email={participant.email}
                    personId={participant.personId}
                />
            ))}
            {hiddenParticipants.length > 0 && (
                <LemonDropdown
                    closeOnClickInside={false}
                    placement="bottom-start"
                    overlay={
                        <div className="flex max-h-80 min-w-56 flex-col gap-2 overflow-y-auto p-3">
                            {participants.map((participant) => (
                                <Person
                                    key={participant.key}
                                    name={participant.name}
                                    email={participant.email}
                                    personId={participant.personId}
                                />
                            ))}
                        </div>
                    }
                >
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        noPadding
                        className="text-muted"
                        data-attr="account-conversations-participant-overflow"
                    >
                        +{hiddenParticipants.length} more
                    </LemonButton>
                </LemonDropdown>
            )}
        </span>
    )
}

function Person({ name, email, personId }: { name: string; email?: string; personId?: string | null }): JSX.Element {
    const content = (
        <span className="inline-flex items-center gap-1.5 min-w-0">
            <ProfilePicture user={{ email: email ?? name }} size="xs" />
            <span className="truncate">{name}</span>
        </span>
    )
    return personId ? <Link to={urls.personByUUID(personId)}>{content}</Link> : content
}

function LatestMessageActivity({ message }: { message: ConversationMessageSummaryApi }): JSX.Element {
    const person = (
        <Person
            name={message.sender.name || message.sender.email || 'Unknown sender'}
            email={message.sender.email ?? undefined}
            personId={message.sender.person_id}
        />
    )
    const sender = message.sender.distinct_id ? (
        <Link to={urls.personByDistinctId(message.sender.distinct_id)}>{person}</Link>
    ) : (
        person
    )

    return (
        <span className="flex min-w-0 flex-col gap-0.5">
            {sender}
            <span className="flex self-start items-center gap-1 text-xs text-muted">
                <span>{message.direction === 'inbound' ? 'Inbound' : 'Outbound'}</span>
                <span>·</span>
                <ActivityTimestamp time={message.sent_at} />
            </span>
        </span>
    )
}

function LatestActivity({ conversation }: { conversation: AccountConversation }): JSX.Element {
    if (conversation.source === 'slack') {
        return (
            <span className="flex flex-col gap-0.5">
                <span>Summary generated</span>
                <ActivityTimestamp time={conversation.summary.generated_at} />
            </span>
        )
    }

    const lastMessage =
        conversation.source === 'email' ? conversation.email.last_message : conversation.ticket.last_message
    if (lastMessage) {
        return <LatestMessageActivity message={lastMessage} />
    }
    return conversation.occurredAt ? (
        <ActivityTimestamp time={conversation.occurredAt} />
    ) : (
        <span className="text-muted">—</span>
    )
}

function EmailMessage({ message }: { message: AccountEmailThreadMessageApi }): JSX.Element {
    const outgoing = message.direction === 'outbound'
    return (
        <div className={`flex ${outgoing ? 'justify-end' : 'justify-start'}`}>
            <LemonCard
                hoverEffect={false}
                className={`p-3 flex flex-col gap-1 max-w-3xl ${outgoing ? 'bg-surface-primary' : 'bg-surface-secondary'}`}
            >
                <div className="flex items-center justify-between gap-4">
                    <Person name={message.sender.name || message.sender.email} email={message.sender.email} />
                    <ActivityTimestamp time={message.sent_at} />
                </div>
                <div className="whitespace-pre-wrap break-words text-sm">{message.content}</div>
            </LemonCard>
        </div>
    )
}

function SupportMessage({ message }: { message: AccountSupportTicketMessageApi }): JSX.Element {
    const outgoing = message.direction === 'outbound'
    return (
        <div className={`flex ${outgoing ? 'justify-end' : 'justify-start'}`}>
            <LemonCard
                hoverEffect={false}
                className={`flex max-w-3xl flex-col gap-1 p-3 ${
                    message.is_private
                        ? 'bg-warning-highlight'
                        : outgoing
                          ? 'bg-surface-primary'
                          : 'bg-surface-secondary'
                }`}
            >
                <div className="flex items-center justify-between gap-4">
                    <span className="flex items-center gap-1.5">
                        <span className="font-medium">{message.author_name}</span>
                        {message.is_private && (
                            <span className="flex items-center gap-1 text-xs text-warning-dark">
                                <IconLock /> Private note
                            </span>
                        )}
                    </span>
                    <ActivityTimestamp time={message.created_at} />
                </div>
                <div className="whitespace-pre-wrap break-words text-sm">{message.content}</div>
            </LemonCard>
        </div>
    )
}

function ConversationDetail({
    accountId,
    conversation,
}: {
    accountId: string
    conversation: AccountConversation
}): JSX.Element {
    const emailLogic = accountEmailThreadsLogic({ accountId })
    const { threadDetails, threadDetailsLoading, threadDetailErrors, threadDetailPages } = useValues(emailLogic)
    const {
        expandedSummaryMessageIds,
        supportTicketMessages,
        supportTicketMessagesLoading,
        supportTicketMessageErrors,
    } = useValues(accountConversationsLogic({ accountId }))
    const { toggleSummaryMessages } = useActions(accountConversationsLogic({ accountId }))
    const { setThreadDetailPage } = useActions(emailLogic)

    if (conversation.source === 'slack') {
        return (
            <div className="flex flex-col gap-4 bg-surface-primary p-4">
                <LemonMarkdown lowKeyHeadings disableImages disableDocsRedirect>
                    {conversation.summary.content}
                </LemonMarkdown>
                {conversation.summary.messages.length > 0 && (
                    <div className="flex flex-col gap-2 border-t pt-3">
                        <LemonButton
                            type="tertiary"
                            fullWidth
                            noPadding
                            className="justify-between"
                            sideIcon={
                                <IconChevronDown
                                    className={
                                        expandedSummaryMessageIds[conversation.summary.id] ? 'rotate-180' : undefined
                                    }
                                />
                            }
                            aria-expanded={!!expandedSummaryMessageIds[conversation.summary.id]}
                            onClick={() => toggleSummaryMessages(conversation.summary.id)}
                            data-attr="account-summary-messages-toggle"
                        >
                            {conversation.summary.message_count}{' '}
                            {conversation.summary.message_count === 1 ? 'message' : 'messages'} summarized
                        </LemonButton>
                        {expandedSummaryMessageIds[conversation.summary.id] && (
                            <div className="flex flex-col gap-1">
                                {conversation.summary.messages.map((message, index) => (
                                    <Link
                                        key={`${message.permalink}-${index}`}
                                        to={message.permalink}
                                        target="_blank"
                                        className="flex items-center justify-between gap-4 rounded px-2 py-1 hover:bg-surface-secondary"
                                    >
                                        <span className="font-medium">{message.author}</span>
                                        <ActivityTimestamp time={message.sent_at} />
                                    </Link>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
        )
    }
    if (conversation.source === 'support') {
        const messages = supportTicketMessages[conversation.ticket.id]
        if (
            supportTicketMessagesLoading[conversation.ticket.id] ||
            (!messages && !supportTicketMessageErrors[conversation.ticket.id])
        ) {
            return <LemonSkeleton className="h-40 w-full" />
        }
        if (!messages || supportTicketMessageErrors[conversation.ticket.id]) {
            return <EmptyState title="Couldn't load this ticket" detail="Collapse it and try again." />
        }
        return (
            <div className="flex flex-col gap-3 bg-surface-primary p-4">
                <div className="flex justify-end">
                    <LemonButton type="secondary" to={conversation.ticket.deep_link} targetBlank>
                        Open in Support
                    </LemonButton>
                </div>
                {messages.results.length > 0 ? (
                    messages.results.map((message) => <SupportMessage key={message.id} message={message} />)
                ) : (
                    <span className="text-sm text-muted">No messages in this ticket yet.</span>
                )}
                {messages.count > messages.results.length && (
                    <span className="text-xs text-muted">
                        Showing {messages.results.length} of {messages.count} messages.
                    </span>
                )}
            </div>
        )
    }

    const detail = threadDetails[conversation.email.id]
    if (threadDetailsLoading[conversation.email.id] || (!detail && !threadDetailErrors[conversation.email.id])) {
        return <LemonSkeleton className="h-40 w-full" />
    }
    if (!detail || threadDetailErrors[conversation.email.id]) {
        return <EmptyState title="Couldn't load this conversation" detail="Collapse it and try again." />
    }
    const page = threadDetailPages[conversation.email.id] ?? 1
    return (
        <div className="flex flex-col gap-2 bg-surface-primary p-4" data-attr="account-email-thread-detail">
            {detail.results.map((message) => (
                <EmailMessage key={message.id} message={message} />
            ))}
            <PaginationControl
                pagination={{ controlled: true, pageSize: MESSAGE_PAGE_SIZE }}
                currentPage={page}
                setCurrentPage={(newPage) => setThreadDetailPage(conversation.email.id, newPage)}
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

function conversationTitle(conversation: AccountConversation): string {
    if (conversation.source === 'email') {
        return conversation.email.subject || 'No subject'
    }
    if (conversation.source === 'support') {
        return `Ticket: #${conversation.ticket.ticket_number}`
    }
    return periodLabel(conversation.summary)
}

function conversationPreview(conversation: AccountConversation): string {
    if (conversation.source === 'email') {
        return conversation.email.preview
    }
    if (conversation.source === 'support') {
        return conversation.ticket.last_message_text ?? ''
    }
    return conversation.summary.content
        .replace(/[#*_`>[\]]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
}

export function AccountConversationsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountConversationsLogic({ accountId })
    const emailLogic = accountEmailThreadsLogic({ accountId })
    const {
        conversationsResult,
        conversationsResultLoading,
        filteredConversations,
        searchTerm,
        sources,
        expandedConversationId,
        olderConversationCount,
    } = useValues(logic)
    const { setSearchTerm, setSources, openConversation, closeConversation, loadConversations, loadMoreConversations } =
        useActions(logic)
    const { openThread, closeThread } = useActions(emailLogic)

    if (
        conversationsResult === NOT_LOADED ||
        (conversationsResultLoading && conversationsResult.conversations === null)
    ) {
        return <LemonSkeleton className="h-64 w-full" />
    }
    const toolbar = (
        <div className="hide-scrollbar flex items-center gap-4 overflow-x-auto pb-1">
            <LemonInput
                type="search"
                value={searchTerm}
                onChange={setSearchTerm}
                placeholder="Search conversations"
                size="small"
                className="min-w-56 max-w-md flex-1"
                data-attr="account-conversations-search"
            />
            <SourceFilter sources={sources} onChange={setSources} />
            <div className="ml-auto flex shrink-0 items-center gap-2 whitespace-nowrap">
                <span className="text-sm text-muted">Slack summary cadence</span>
                <AccountSummaryCadencePicker accountId={accountId} />
            </div>
        </div>
    )
    const sourceFailureBanner = conversationsResult.failedSources.length > 0 && (
        <LemonBanner
            type={conversationsResult.loadFailed ? 'error' : 'warning'}
            action={{
                children: 'Retry',
                onClick: loadConversations,
                loading: conversationsResultLoading,
            }}
        >
            {conversationsResult.loadFailed
                ? "Conversation sources couldn't load."
                : "Some conversation sources aren't available. Showing the sources that loaded."}
        </LemonBanner>
    )
    if (conversationsResult.loadFailed) {
        return (
            <div className="flex flex-col gap-3">
                {toolbar}
                {sourceFailureBanner}
                <EmptyState title="Couldn't load conversations" detail="Retry to load this account's conversations." />
            </div>
        )
    }
    if (!conversationsResult.conversations?.length) {
        return (
            <div className="flex flex-col gap-3">
                {toolbar}
                {sourceFailureBanner}
                <EmptyState
                    title="No conversations yet"
                    detail="Email, Support, and Slack conversations will appear here."
                />
            </div>
        )
    }

    const toggleConversation = (conversation: AccountConversation): void => {
        if (expandedConversationId === conversation.id) {
            closeConversation(conversation.id)
            if (conversation.source === 'email') {
                closeThread(conversation.email.id)
            }
        } else {
            openConversation(conversation.id)
            if (conversation.source === 'email') {
                openThread(conversation.email.id)
            }
        }
    }

    const columns: LemonTableColumns<AccountConversation> = [
        {
            title: 'Conversation',
            key: 'conversation',
            align: 'left',
            render: (_, conversation) => (
                <LemonButton
                    type="tertiary"
                    noPadding
                    fullWidth
                    className="justify-start text-left"
                    aria-expanded={expandedConversationId === conversation.id}
                    onClick={() => toggleConversation(conversation)}
                >
                    <span className="flex min-w-0 items-center gap-2 py-1">
                        <SourceIcon source={conversation.source} />
                        <span className="flex min-w-0 flex-col">
                            <span className="font-medium truncate">{conversationTitle(conversation)}</span>
                            <span className="text-xs text-muted line-clamp-2">{conversationPreview(conversation)}</span>
                        </span>
                    </span>
                </LemonButton>
            ),
        },
        {
            title: 'Started by',
            key: 'startedBy',
            align: 'left',
            render: (_, conversation) => {
                if (conversation.source === 'email') {
                    const starter = conversation.email.first_message?.sender
                    return starter ? (
                        <Person
                            name={starter.name || starter.email || 'Unknown sender'}
                            email={starter.email ?? undefined}
                            personId={starter.person_id}
                        />
                    ) : (
                        <span className="text-muted">—</span>
                    )
                }
                if (conversation.source === 'support') {
                    return (
                        <Link to={urls.personByDistinctId(conversation.ticket.distinct_id)}>
                            <Person name={conversation.ticket.started_by} />
                        </Link>
                    )
                }
                const author = conversation.summary.messages[0]?.author
                return author ? <Person name={author} /> : <span className="text-muted">—</span>
            },
        },
        {
            title: 'Latest activity',
            key: 'latestActivity',
            align: 'left',
            width: 190,
            render: (_, conversation) => <LatestActivity conversation={conversation} />,
        },
        {
            title: 'Participants',
            key: 'participants',
            align: 'left',
            render: (_, conversation) => {
                if (conversation.source === 'email') {
                    return (
                        <ParticipantList
                            participants={conversation.email.participants.map((participant) => ({
                                key: participant.email,
                                name: participant.display_name || participant.email,
                                email: participant.email,
                                personId: participant.kind === 'customer' ? participant.person_id : null,
                            }))}
                        />
                    )
                }
                if (conversation.source === 'support') {
                    return <Person name={conversation.ticket.started_by} />
                }
                const authors = [...new Set(conversation.summary.messages.map((message) => message.author))]
                return <ParticipantList participants={authors.map((author) => ({ key: author, name: author }))} />
            },
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            {toolbar}
            {sourceFailureBanner}
            <LemonTable<AccountConversation>
                data-attr="account-conversations-table"
                size="small"
                embedded
                dataSource={filteredConversations}
                columns={columns}
                rowKey="id"
                tableLayout="fixed"
                pagination={{ pageSize: 10, useUrl: false }}
                expandable={{
                    expandedRowRender: (conversation) => (
                        <ConversationDetail accountId={accountId} conversation={conversation} />
                    ),
                    isRowExpanded: (conversation) => conversation.id === expandedConversationId,
                    rowExpandable: () => true,
                    showRowExpansionToggle: false,
                    noIndent: true,
                }}
                emptyState={
                    olderConversationCount > 0
                        ? 'No loaded conversations match. Load older conversations to search more.'
                        : 'No conversations match your search and filters.'
                }
            />
            {olderConversationCount > 0 && (
                <div className="flex items-center justify-end gap-3">
                    <span className="text-xs text-muted">
                        {olderConversationCount} older {olderConversationCount === 1 ? 'conversation' : 'conversations'}{' '}
                        not loaded
                    </span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={conversationsResultLoading}
                        onClick={loadMoreConversations}
                    >
                        Load older conversations
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
