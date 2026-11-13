import type { ChatMessage, MessageDeliveryStatus } from '../../types'

const CONFIRMATION_FAILED_REASON =
    "We couldn't deliver the confirmation email, so replies on this ticket are not emailed. Check the email channel settings and the customer's email address."
const REPLY_FAILED_REASON =
    "We couldn't deliver this email reply. Please check the email channel settings and contact support if the issue persists."

export interface MessageDeliveryLabel {
    text: string
    failureReason?: string
}

export function messageDeliveryLabel(
    message: Pick<ChatMessage, 'emailDeliveryStatus' | 'isEmailConfirmation'>,
    deliveryStatus: MessageDeliveryStatus | undefined
): MessageDeliveryLabel | null {
    if (message.emailDeliveryStatus === 'failed') {
        return {
            text: 'Failed to send',
            failureReason: message.isEmailConfirmation ? CONFIRMATION_FAILED_REASON : REPLY_FAILED_REASON,
        }
    }
    if (message.emailDeliveryStatus === 'sending') {
        return { text: 'Sending…' }
    }
    // A private note has no read receipt, so the email status is its only delivery signal.
    if (message.isEmailConfirmation && message.emailDeliveryStatus === 'sent') {
        return { text: 'Sent' }
    }
    if (!deliveryStatus) {
        return null
    }
    return { text: deliveryStatus === 'read' ? 'Read' : 'Sent' }
}
