import { messageDeliveryLabel } from './messageDeliveryLabel'

describe('messageDeliveryLabel', () => {
    it.each([
        [
            'a reply whose email failed',
            { emailDeliveryStatus: 'failed' as const },
            'sent' as const,
            'Failed to send',
            'this email reply',
        ],
        [
            'a confirmation note whose email failed',
            { emailDeliveryStatus: 'failed' as const, isEmailConfirmation: true },
            undefined,
            'Failed to send',
            'the confirmation email',
        ],
        [
            'an email still being sent',
            { emailDeliveryStatus: 'sending' as const },
            'sent' as const,
            'Sending…',
            undefined,
        ],
        [
            'a confirmation note whose email was sent',
            { emailDeliveryStatus: 'sent' as const, isEmailConfirmation: true },
            undefined,
            'Sent',
            undefined,
        ],
        ['a private note with no email', {}, undefined, null, undefined],
        [
            'a message the customer has read',
            { emailDeliveryStatus: 'sent' as const },
            'read' as const,
            'Read',
            undefined,
        ],
    ])('labels %s', (_name, message, deliveryStatus, expectedText, expectedReasonPart) => {
        const label = messageDeliveryLabel(message, deliveryStatus)

        expect(label?.text ?? null).toBe(expectedText)
        expect(label?.failureReason?.includes(expectedReasonPart ?? '') ?? false).toBe(expectedReasonPart !== undefined)
    })
})
