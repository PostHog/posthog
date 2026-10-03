import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { bodyParagraph, exceptionChain, signalPreview } from './todaySignalPreview'
import { signal } from './todayTestFixtures'

describe('todaySignalPreview', () => {
    test('reads a stack trace as a chain of causes, each at its deepest frame in the team’s own code', () => {
        const content = [
            'New error tracking issue created - this particular exception was observed for the first time:',
            'JobError: the job failed with UploadError',
            '',
            '```',
            'JobError: the job failed with UploadError',
            'run in posthog/jobs/runner.py line 40',
            'start_upload in products/files/backend/upload.py line 12',
            'UploadError: Failed to upload',
            'put in products/files/backend/storage.py line 88',
            'send in boto3/client.py line 300',
            '```',
        ].join('\n')
        expect(exceptionChain(content)).toEqual([
            { text: '  upload.py:12  start_upload', quiet: true },
            { text: 'Caused by UploadError: Failed to upload', quiet: false },
            { text: '  storage.py:88  put', quiet: true },
        ])
    })

    test.each([
        [
            'the paragraph under a title line',
            'Title line\nFirst paragraph.\n\nPart of #12.',
            undefined,
            'First paragraph.',
        ],
        [
            'the labelled section',
            'Title\n\n**Product area:** Billing\n\n**Issue:** The invoice is blank.\n\n**Resolution:** Fixed.',
            'Issue',
            'The invoice is blank.',
        ],
        ['nothing for a title alone', 'Title only', undefined, null],
    ])('finds %s', (_, content, label, expected) => {
        expect(bodyParagraph(content, label)).toEqual(expected)
    })

    test.each([
        [
            'a recording, which plays at once',
            signal({
                source_product: 'replay_vision',
                content: 'A button does nothing.',
                extra: { session_id: 's1' } as SignalNodeApi['extra'],
            }),
            null,
        ],
        [
            'a Slack finding with nothing past its headline, which links straight to the thread',
            signal({ content: 'A teammate said the banner is too loud. https://example.slack.com/archives/C1/p1' }),
            null,
        ],
        [
            'the query behind a pganalyze issue',
            signal({
                source_product: 'pganalyze',
                content: 'Query #1 takes 95 ms on average',
                extra: {
                    references: [{ kind: 'Query', queryText: 'SELECT ... FROM orders' }],
                } as SignalNodeApi['extra'],
            }),
            expect.objectContaining({
                hint: 'Show the query',
                block: [{ text: 'SELECT ... FROM orders', quiet: false }],
                open: null,
            }),
        ],
        [
            'the description of a GitHub issue',
            signal({
                source_product: 'github',
                source_type: 'issue',
                content: 'Checkout drops the coupon\nThe cart forgets the coupon code after a refresh.\n\nPart of #12.',
                extra: {
                    html_url: 'https://github.com/example/shop/issues/7',
                    number: 7,
                    state: 'open',
                } as SignalNodeApi['extra'],
            }),
            expect.objectContaining({
                hint: 'Show the description',
                text: 'The cart forgets the coupon code after a refresh.',
                open: { to: 'https://github.com/example/shop/issues/7', external: true, label: 'Open on GitHub' },
            }),
        ],
    ])('previews %s', (_, item, expected) => {
        expect(signalPreview(item)).toEqual(expected)
    })
})
