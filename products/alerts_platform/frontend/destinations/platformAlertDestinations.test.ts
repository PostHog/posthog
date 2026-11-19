import { describePendingDestination } from './platformAlertDestinations'

describe('describePendingDestination', () => {
    it('shows only the scheme and host of a webhook URL, whose path carries its secret', () => {
        expect(
            describePendingDestination({ type: 'discord', webhook_url: 'https://discord.com/api/webhooks/123/s3cr3t' })
        ).toEqual({ title: 'Discord', detail: 'https://discord.com' })
    })
})
