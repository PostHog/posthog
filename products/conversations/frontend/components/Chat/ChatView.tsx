import { JSONContent } from '@tiptap/core'

import { LemonCard } from '@posthog/lemon-ui'

import type { QuickActionActionsApi, QuickActionApi } from '../../generated/api.schemas'
import type { AiReplyFeedbackRating, ChatMessage, Ticket, TicketChannel, TicketStatus } from '../../types'
import { TemplateVariableValues } from '../Editor/templateVariables'
import { MessageInput } from './MessageInput'
import { MessageList } from './MessageList'

export interface ChatViewProps {
    messages: ChatMessage[]
    messagesLoading: boolean
    messageSending: boolean
    hasMoreMessages?: boolean
    olderMessagesLoading?: boolean
    ticket?: Ticket
    onSendMessage: (
        content: string,
        richContent: JSONContent | null,
        isPrivate: boolean,
        onSuccess: () => void,
        statusAfterSend?: TicketStatus
    ) => void
    onLoadOlderMessages?: () => void
    header?: React.ReactNode
    minHeight?: string
    maxHeight?: string
    /** Channel the ticket came from; drives the reply placeholder and send-button logo */
    channel?: TicketChannel
    /** Whether to show the "Send as private" option in the message input */
    showPrivateOption?: boolean
    /** Number of team messages that haven't been read by the customer */
    unreadCustomerCount?: number
    /** Whether to show delivery status on team messages */
    showDeliveryStatus?: boolean
    /** Draft content to restore (for tab persistence) */
    draftContent?: JSONContent | null
    /** Called when draft content changes */
    onDraftChange?: (content: JSONContent | null) => void
    /** Whether the private note checkbox is checked */
    isPrivate?: boolean
    /** Called when private checkbox changes */
    onPrivateChange?: (isPrivate: boolean) => void
    /** Extra actions rendered next to the send button in MessageInput */
    extraActions?: React.ReactNode
    /** Blocks sending customer-facing messages (private notes stay available) */
    replyDisabledReason?: string | JSX.Element
    /** Whether draft mode is on: tints the composer green and confirms the recipient before sending */
    draftMode?: boolean
    /** Called when the draft-mode toggle changes */
    onDraftModeChange?: (enabled: boolean) => void
    /** Recipient description shown in the draft-mode send confirmation */
    sendConfirmationMessage?: string
    /** When provided, renders a dropdown next to the send button to send and set the ticket status in one go */
    sendAndSetStatusOptions?: { value: TicketStatus; statusLabel: string }[]
    /** Other unsaved ticket edits that sending with a status would also persist */
    unsavedTicketChanges?: string[]
    latestAiMessageId?: string | null
    feedbackByMessageId?: Record<string, AiReplyFeedbackRating>
    showAiReplyFeedback?: boolean
    onSubmitAiReplyFeedback?: (messageId: string, rating: AiReplyFeedbackRating, feedbackText?: string) => void
    /** Enables the `/` quick-action slash command and the quick-action toolbar button */
    enableQuickActions?: boolean
    /** Values used to fill {{variable}} tokens when a response quick action is inserted */
    templateVariables?: TemplateVariableValues
    /** Applies a response quick action's ticket actions (status/assignee/tags/priority) */
    onApplyTicketActions?: (actions: QuickActionActionsApi) => void
    /** Runs a workflow quick action against the ticket */
    onRunWorkflow?: (quickAction: QuickActionApi) => void
}

export function ChatView({
    messages,
    messagesLoading,
    messageSending,
    hasMoreMessages = false,
    olderMessagesLoading = false,
    onSendMessage,
    onLoadOlderMessages,
    header,
    minHeight,
    maxHeight,
    channel,
    showPrivateOption = false,
    unreadCustomerCount,
    showDeliveryStatus = false,
    draftContent,
    onDraftChange,
    isPrivate,
    onPrivateChange,
    extraActions,
    replyDisabledReason,
    draftMode,
    onDraftModeChange,
    sendConfirmationMessage,
    sendAndSetStatusOptions,
    unsavedTicketChanges,
    latestAiMessageId,
    feedbackByMessageId,
    showAiReplyFeedback,
    onSubmitAiReplyFeedback,
    enableQuickActions,
    templateVariables,
    onApplyTicketActions,
    onRunWorkflow,
}: ChatViewProps): JSX.Element {
    const listMinHeight = minHeight ?? '400px'
    const listMaxHeight = maxHeight ?? '600px'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden p-3">
            {header}
            <MessageList
                messages={messages}
                messagesLoading={messagesLoading}
                hasMoreMessages={hasMoreMessages}
                olderMessagesLoading={olderMessagesLoading}
                onLoadOlderMessages={onLoadOlderMessages}
                emptyMessage="No messages yet. Start the conversation!"
                minHeight={listMinHeight}
                maxHeight={listMaxHeight}
                unreadCustomerCount={unreadCustomerCount}
                showDeliveryStatus={showDeliveryStatus}
                latestAiMessageId={latestAiMessageId}
                feedbackByMessageId={feedbackByMessageId}
                showAiReplyFeedback={showAiReplyFeedback}
                onSubmitAiReplyFeedback={onSubmitAiReplyFeedback}
            />
            <div className="border-t pt-3">
                <MessageInput
                    onSendMessage={onSendMessage}
                    messageSending={messageSending}
                    channel={channel}
                    showPrivateOption={showPrivateOption}
                    draftContent={draftContent}
                    onDraftChange={onDraftChange}
                    isPrivate={isPrivate}
                    onPrivateChange={onPrivateChange}
                    extraActions={extraActions}
                    replyDisabledReason={replyDisabledReason}
                    draftMode={draftMode}
                    onDraftModeChange={onDraftModeChange}
                    sendConfirmationMessage={sendConfirmationMessage}
                    sendAndSetStatusOptions={sendAndSetStatusOptions}
                    unsavedTicketChanges={unsavedTicketChanges}
                    enableQuickActions={enableQuickActions}
                    templateVariables={templateVariables}
                    onApplyTicketActions={onApplyTicketActions}
                    onRunWorkflow={onRunWorkflow}
                />
            </div>
        </LemonCard>
    )
}
