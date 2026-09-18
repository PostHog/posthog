import { selectEmailSenderIntegrationId } from './email-sender-selection'

describe('selectEmailSenderIntegrationId', () => {
    it.each([
        ['keeps the legacy sender when no rotation is configured', { integrationId: 7 }, 7],
        ['uses the only sender in a configured list', { integrationId: 7, integrationIds: [11] }, 11],
        ['ignores duplicate sender ids', { integrationId: 7, integrationIds: [11, 11] }, 11],
    ])('%s', (_name, sender, expected) => {
        expect(selectEmailSenderIntegrationId('invocation-1', sender)).toBe(expected)
    })

    it('returns the same sender for retries and reordered sender lists', () => {
        const selected = selectEmailSenderIntegrationId('invocation-42', {
            integrationId: 11,
            integrationIds: [11, 22, 33],
        })

        expect(
            selectEmailSenderIntegrationId('invocation-42', {
                integrationId: 33,
                integrationIds: [33, 11, 22],
            })
        ).toBe(selected)
    })

    it('distributes workflow invocations across the configured senders', () => {
        const counts = new Map<number, number>([
            [11, 0],
            [22, 0],
            [33, 0],
        ])

        for (let index = 0; index < 900; index++) {
            const selected = selectEmailSenderIntegrationId(`invocation-${index}`, {
                integrationId: 11,
                integrationIds: [11, 22, 33],
            })
            counts.set(selected, (counts.get(selected) ?? 0) + 1)
        }

        for (const count of counts.values()) {
            expect(count).toBeGreaterThan(250)
            expect(count).toBeLessThan(350)
        }
    })
})
