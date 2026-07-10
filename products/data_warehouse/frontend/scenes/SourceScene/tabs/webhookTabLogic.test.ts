import { syncWebhookEventsToast } from './webhookTabLogic'

describe('syncWebhookEventsToast', () => {
    // Regression: a source without automatic reconcile support (base no-op sync_webhook_events)
    // returns success while missing_events stays non-empty. That must not be announced as the
    // provider webhook having been updated.
    it.each([
        {
            case: 'success with remaining missing events is not reported as updated',
            success: true,
            error: null,
            missingEvents: ['customer.created'],
            expectedType: 'info' as const,
        },
        {
            case: 'success with cleared missing events reports updated',
            success: true,
            error: null,
            missingEvents: [],
            expectedType: 'success' as const,
        },
        {
            case: 'success without missing events reports updated',
            success: true,
            error: null,
            missingEvents: undefined,
            expectedType: 'success' as const,
        },
        {
            case: 'provider failure reports the error',
            success: false,
            error: 'Permission denied',
            missingEvents: ['customer.created'],
            expectedType: 'error' as const,
        },
    ])('$case', ({ success, error, missingEvents, expectedType }) => {
        const toast = syncWebhookEventsToast(success, error, missingEvents)
        expect(toast.type).toBe(expectedType)
        if (expectedType === 'error') {
            expect(toast.message).toBe('Permission denied')
        }
    })
})
