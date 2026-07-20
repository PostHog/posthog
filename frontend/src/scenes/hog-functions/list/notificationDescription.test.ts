import { getNotificationDescription } from './notificationDescription'

describe('getNotificationDescription', () => {
    test.each([
        [{ url: { value: 'https://hooks.example.com/path' } }, 'hooks.example.com'],
        [{ url: { value: 'not a valid URL' } }, 'not a valid URL'],
        [{ channel: { value: '#alerts' } }, '#alerts'],
        [{ email: { value: 'alerts@example.com' } }, 'alerts@example.com'],
        [undefined, null],
    ])('returns the destination description for inputs %#', (inputs, expected) => {
        expect(getNotificationDescription({ inputs })).toBe(expected)
    })
})
