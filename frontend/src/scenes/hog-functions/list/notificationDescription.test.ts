import { getNotificationDescription } from './notificationDescription'

describe('getNotificationDescription', () => {
    test.each([
        [{ url: { value: 'https://hooks.example.com/path' } }, 'hooks.example.com'],
        [{ url: { value: 'not a valid URL' } }, 'not a valid URL'],
        [{ webhookUrl: { value: 'https://discord.com/api/webhooks/123/token' } }, 'discord.com'],
        [{ webhookUrl: { value: 'not a valid webhook URL' } }, 'not a valid webhook URL'],
        [{ channel: { value: '#alerts' } }, '#alerts'],
        [{ email: { value: 'alerts@example.com' } }, 'alerts@example.com'],
        [undefined, null],
    ])('returns the destination description for inputs %#', (inputs, expected) => {
        expect(getNotificationDescription({ inputs })).toBe(expected)
    })
})
