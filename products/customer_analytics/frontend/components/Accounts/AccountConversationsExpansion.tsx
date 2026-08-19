import { useActions, useValues } from 'kea'

import { IconSupport } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonInputSelect,
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
import { urls } from 'scenes/urls'

import gmailIcon from 'public/services/gmail.png'

import type {
    AccountEmailThreadMessageApi,
    AccountEmailThreadParticipantApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    AccountConversation,
    accountConversationsLogic,
    ConversationSource,
    NOT_LOADED,
} from './accountConversationsLogic'
import { accountEmailThreadsLogic } from './accountEmailThreadsLogic'
import { periodLabel } from './AccountSummariesExpansion'
import { AccountSummaryCadencePicker } from './AccountSummaryCadencePicker'

const SOURCE_OPTIONS = [
    { key: 'email', label: 'Gmail' },
    { key: 'support', label: 'Support' },
    { key: 'slack', label: 'Slack' },
]

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
            <span className="inline-flex text-lg" aria-label={label}>
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

function Person({ name, email, personId }: { name: string; email?: string; personId?: string | null }): JSX.Element {
    const content = (
        <span className="inline-flex items-center gap-1.5 min-w-0">
            <ProfilePicture user={{ email: email ?? name }} size="xs" />
            <span className="truncate">{name}</span>
        </span>
    )
    return personId ? <Link to={urls.personByUUID(personId)}>{content}</Link> : content
}

function EmailParticipant({ participant }: { participant: AccountEmailThreadParticipantApi }): JSX.Element {
    return (
        <Person
            name={participant.display_name || participant.email}
            email={participant.email}
            personId={participant.kind === 'customer' ? participant.person_id : null}
        />
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
                    <TZLabel time={message.sent_at} />
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
    const { threadDetails, threadDetailsLoading, threadDetailErrors } = useValues(emailLogic)

    if (conversation.source === 'slack') {
        return (
            <LemonCard hoverEffect={false} className="p-4">
                <LemonMarkdown lowKeyHeadings disableImages disableDocsRedirect>
                    {conversation.summary.content}
                </LemonMarkdown>
            </LemonCard>
        )
    }
    if (conversation.source === 'support') {
        return (
            <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-3">
                <p className="mb-0 whitespace-pre-wrap">
                    {conversation.ticket.last_message_text || 'No message preview.'}
                </p>
                <LemonButton type="secondary" to={conversation.ticket.deep_link} targetBlank className="self-start">
                    Open in Support
                </LemonButton>
            </LemonCard>
        )
    }

    const detail = threadDetails[conversation.email.id]
    if (threadDetailsLoading[conversation.email.id] || (!detail && !threadDetailErrors[conversation.email.id])) {
        return <LemonSkeleton className="h-40 w-full" />
    }
    if (!detail || threadDetailErrors[conversation.email.id]) {
        return <EmptyState title="Couldn't load this conversation" detail="Collapse it and try again." />
    }
    return (
        <div className="flex flex-col gap-2 py-2">
            {detail.results.map((message) => (
                <EmailMessage key={message.id} message={message} />
            ))}
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
    } = useValues(logic)
    const { setSearchTerm, setSources, openConversation, closeConversation } = useActions(logic)
    const { openThread, closeThread } = useActions(emailLogic)

    if (conversationsResult === NOT_LOADED || conversationsResultLoading) {
        return <LemonSkeleton className="h-64 w-full" />
    }
    if (conversationsResult.loadFailed) {
        return <EmptyState title="Couldn't load conversations" detail="Refresh the page to try again." />
    }
    if (!conversationsResult.conversations?.length) {
        return (
            <EmptyState
                title="No conversations yet"
                detail="Email, Support, and Slack conversations will appear here."
            />
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
            key: 'id',
            render: (_, conversation) => (
                <LemonButton
                    type="tertiary"
                    noPadding
                    fullWidth
                    className="justify-start text-left"
                    aria-expanded={expandedConversationId === conversation.id}
                    onClick={() => toggleConversation(conversation)}
                >
                    <span className="flex flex-col min-w-0 py-1">
                        <span className="font-medium truncate">{conversationTitle(conversation)}</span>
                        <span className="text-xs text-muted truncate">{conversationPreview(conversation)}</span>
                    </span>
                </LemonButton>
            ),
        },
        {
            title: 'Source',
            key: 'source',
            width: 70,
            render: (_, conversation) => <SourceIcon source={conversation.source} />,
        },
        {
            title: 'Started by',
            key: 'id',
            render: (_, conversation) => {
                if (conversation.source === 'email') {
                    const starter = conversation.email.participants[0]
                    return starter ? <EmailParticipant participant={starter} /> : <span className="text-muted">—</span>
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
            title: 'Last message',
            key: 'occurredAt',
            width: 145,
            render: (_, conversation) =>
                conversation.occurredAt ? (
                    <TZLabel time={conversation.occurredAt} />
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: 'Participants',
            key: 'id',
            render: (_, conversation) => {
                if (conversation.source === 'email') {
                    return (
                        <span className="flex flex-wrap gap-2">
                            {conversation.email.participants.slice(0, 3).map((participant) => (
                                <EmailParticipant key={participant.email} participant={participant} />
                            ))}
                        </span>
                    )
                }
                if (conversation.source === 'support') {
                    return <Person name={conversation.ticket.started_by} />
                }
                const authors = [...new Set(conversation.summary.messages.map((message) => message.author))]
                return (
                    <span className="flex flex-wrap gap-2">
                        {authors.slice(0, 3).map((author) => (
                            <Person key={author} name={author} />
                        ))}
                    </span>
                )
            },
        },
        {
            title: 'Last message status',
            key: 'id',
            width: 170,
            render: (_, conversation) =>
                conversation.source === 'slack' ? (
                    'Summary generated'
                ) : (
                    <span className="text-muted">Not available</span>
                ),
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-2">
                <LemonInput
                    type="search"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    placeholder="Search conversations"
                    className="max-w-md flex-1"
                    data-attr="account-conversations-search"
                />
                <LemonInputSelect
                    mode="multiple"
                    value={sources}
                    onChange={(values) => setSources(values as ConversationSource[])}
                    options={SOURCE_OPTIONS.map((option) => ({ key: option.key, label: option.label }))}
                    placeholder="All sources"
                    displayMode="count"
                    allowCustomValues={false}
                    data-attr="account-conversations-source-filter"
                />
                <div className="flex items-center gap-2 ml-auto">
                    <span className="text-sm text-muted">Slack summary cadence</span>
                    <AccountSummaryCadencePicker accountId={accountId} />
                </div>
            </div>
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
                emptyState="No conversations match your search and filters."
            />
        </div>
    )
}
