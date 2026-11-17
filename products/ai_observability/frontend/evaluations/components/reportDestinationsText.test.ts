import { reportDestinationsText } from './reportDestinationsText'

describe('reportDestinationsText', () => {
    it.each([
        ['no destination', [], 'Shown only here'],
        ['a Slack channel id without a name', [{ type: 'slack' as const, channel: 'C123' }], 'Sent to #C123'],
        [
            'Slack with a stored name, then several emails',
            [
                { type: 'slack' as const, integration_id: 1, channel: 'C123|#evals' },
                { type: 'email' as const, value: 'a@example.com, b@example.com,' },
            ],
            'Sent to #evals and 2 email addresses',
        ],
    ])('describes %s', (_, targets, expected) => {
        expect(reportDestinationsText(targets)).toBe(expected)
    })
})
