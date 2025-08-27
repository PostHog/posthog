// Mailjet Webhook Event Types
// Based on official Mailjet documentation: https://dev.mailjet.com/email/guides/webhooks/

export type MailjetEventType = 'sent' | 'open' | 'click' | 'bounce' | 'blocked' | 'spam' | 'unsub'

// Base interface shared by all events
export interface MailjetEventBase {
    /** The event type */
    event: MailjetEventType
    /** Unix timestamp when the event occurred */
    time: number
    /** Legacy Message ID (numeric) */
    MessageID: number
    /** Unique 128-bit ID for this message (UUID format) */
    Message_GUID: string
    /** Recipient email address */
    email: string
    /** Mailjet campaign ID */
    mj_campaign_id: number
    /** Mailjet contact ID */
    mj_contact_id: number
    /** Custom campaign identifier */
    customcampaign: string
    /** Custom ID provided when sending (for tracking) */
    CustomID?: string
    /** Custom payload provided when sending */
    Payload?: string
}

// Specific event interfaces
export interface MailjetSentEvent extends MailjetEventBase {
    event: 'sent'
    /** Mailjet message ID (string format) */
    mj_message_id: string
    /** SMTP server response */
    smtp_reply: string
}

export interface MailjetOpenEvent extends MailjetEventBase {
    event: 'open'
    /** IP address where the open occurred */
    ip: string
    /** Geographic location (country code) */
    geo: string
    /** User agent string of the client */
    agent: string
}

export interface MailjetClickEvent extends MailjetEventBase {
    event: 'click'
    /** The URL that was clicked */
    url: string
    /** IP address where the click occurred */
    ip: string
    /** Geographic location (country code) */
    geo: string
    /** User agent string of the client */
    agent: string
}

export interface MailjetBounceEvent extends MailjetEventBase {
    event: 'bounce'
    /** Whether this is a blocked email */
    blocked: boolean
    /** Whether this is a hard bounce (permanent failure) */
    hard_bounce: boolean
    /** What the error is related to (e.g., "recipient", "content") */
    error_related_to: string
    /** Detailed error message */
    error: string
    /** Additional comments about the bounce */
    comment?: string
}

export interface MailjetBlockedEvent extends MailjetEventBase {
    event: 'blocked'
    /** What the error is related to (e.g., "recipient", "content") */
    error_related_to: string
    /** Detailed error message */
    error: string
}

export interface MailjetSpamEvent extends MailjetEventBase {
    event: 'spam'
    /** Source of the spam report (e.g., "JMRPP") */
    source: string
}

export interface MailjetUnsubEvent extends MailjetEventBase {
    event: 'unsub'
    /** Mailjet list ID from which the user unsubscribed */
    mj_list_id: number
    /** IP address where the unsubscribe occurred */
    ip: string
    /** Geographic location (country code) */
    geo: string
    /** User agent string of the client */
    agent: string
}

// Union type for all possible webhook events
export type MailjetWebhookEvent =
    | MailjetSentEvent
    | MailjetOpenEvent
    | MailjetClickEvent
    | MailjetBounceEvent
    | MailjetBlockedEvent
    | MailjetSpamEvent
    | MailjetUnsubEvent

// Event type to category mapping (for your existing code compatibility)
export const EVENT_TYPE_TO_CATEGORY = {
    sent: 'email_sent',
    open: 'email_opened',
    click: 'email_link_clicked',
    bounce: 'email_bounced',
    blocked: 'email_blocked',
    spam: 'email_spam',
    unsub: 'email_unsubscribed',
} as const

// Type guards to narrow event types
export function isSentEvent(event: MailjetWebhookEvent): event is MailjetSentEvent {
    return event.event === 'sent'
}

export function isOpenEvent(event: MailjetWebhookEvent): event is MailjetOpenEvent {
    return event.event === 'open'
}

export function isClickEvent(event: MailjetWebhookEvent): event is MailjetClickEvent {
    return event.event === 'click'
}

export function isBounceEvent(event: MailjetWebhookEvent): event is MailjetBounceEvent {
    return event.event === 'bounce'
}

export function isBlockedEvent(event: MailjetWebhookEvent): event is MailjetBlockedEvent {
    return event.event === 'blocked'
}

export function isSpamEvent(event: MailjetWebhookEvent): event is MailjetSpamEvent {
    return event.event === 'spam'
}

export function isUnsubEvent(event: MailjetWebhookEvent): event is MailjetUnsubEvent {
    return event.event === 'unsub'
}

// Error categorization for bounce/blocked events
export type MailjetErrorType =
    | 'recipient' // Invalid recipient
    | 'content' // Content-related issue
    | 'domain' // Domain-related issue
    | 'reputation' // Sender reputation issue
    | 'policy' // Policy violation
    | 'system' // System error
    | 'timeout' // Connection timeout
    | 'quota' // Quota exceeded
    | 'unknown' // Unknown error

// Common bounce/error reasons
export type MailjetBounceReason =
    | 'user unknown' // Email address doesn't exist
    | 'domain not found' // Domain doesn't exist
    | 'mailbox full' // Recipient's mailbox is full
    | 'message too large' // Message exceeds size limits
    | 'content blocked' // Content triggered spam filters
    | 'policy violation' // Violated sending policy
    | 'reputation blocked' // Sender reputation issue
    | 'rate limit exceeded' // Too many messages sent
    | 'connection timeout' // Connection timed out
    | 'duplicate in campaign' // X-Mailjet-DeduplicateCampaign duplicate
    | 'preblocked' // Address preblocked by Mailjet
    | 'spam content' // Content classified as spam
    | string // Other specific error messages

// Extended interfaces with more specific error typing
export interface MailjetBounceEventTyped extends Omit<MailjetBounceEvent, 'error'> {
    error: MailjetBounceReason
}

export interface MailjetBlockedEventTyped extends Omit<MailjetBlockedEvent, 'error'> {
    error: MailjetBounceReason
}
