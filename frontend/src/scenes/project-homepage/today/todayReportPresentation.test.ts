import { dayjs } from 'lib/dayjs'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'

import {
    signalDestination,
    signalHeadline,
    figureSource,
    findFigures,
    anchorToday,
    highlightSegments,
    scoutLabel,
    signalReading,
    codeExcerpt,
    codeIdentifiers,
    figuresToMark,
    inlineSegments,
    reportWorkKind,
    researchNotes,
    conciseText,
    dailyTrend,
    inFlightPullRequest,
    pickEvidence,
    shortenGitHubLinks,
    signalMeta,
    todayNextStep,
    todayReportSections,
} from './todayReportPresentation'

function signal(overrides: Partial<SignalNodeApi>): SignalNodeApi {
    return {
        signal_id: 'signal-1',
        content: '',
        source_product: 'signals_scout',
        source_type: 'cross_source_issue',
        source_id: 'source-1',
        weight: 1,
        timestamp: '2026-10-01T10:00:00Z',
        extra: {} as SignalNodeApi['extra'],
        ...overrides,
    }
}

function report(overrides: Partial<SignalReport>): SignalReport {
    return {
        id: 'report-1',
        title: 'fix(checkout): keep the billing address',
        summary: 'Lead.',
        status: SignalReportStatus.READY,
        signal_count: 1,
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
        ...overrides,
    } as SignalReport
}

describe('todayReportPresentation', () => {
    test.each([
        [
            'markdown headings',
            'Lead sentence.\n\n## Problem\n\nBroken.\n\n## Impact\n\n**12 people** hit it. [Failures](chart:failures)\n\n## Solution\n\nFix the key.\n\n## Expected impact\n\nZero errors.',
            {
                lead: 'Lead sentence.',
                impact: '**12 people** hit it.',
                proposal: 'Fix the key.',
                expected: 'Zero errors.',
            },
        ],
        [
            'bold paragraph headings',
            'Lead sentence.\n\n**Evidence**\n\n- A finding.\n\n**Recommended next step**\n\n- Inspect the [rate](chart:rate) path.',
            {
                lead: 'Lead sentence.',
                impact: null,
                proposal: '- Inspect the rate path.',
                expected: null,
            },
        ],
        [
            'a bold lead sentence',
            '**One-page checkout won. It is safe to ship.**\n\nThe shorter checkout completed more often.',
            {
                lead: '**One-page checkout won. It is safe to ship.**',
                impact: null,
                proposal: null,
                expected: null,
            },
        ],
        [
            'no headings',
            'Only a lead.\n\nA second paragraph.',
            { lead: 'Only a lead.', impact: null, proposal: null, expected: null },
        ],
    ])('splits a summary with %s', (_, summary, expected) => {
        expect(todayReportSections(summary)).toEqual(expected)
    })

    test.each([
        [
            'replay vision seconds',
            { session_id: 's1', start_time: 108, recording_start_time: '2026-10-02T12:15:23Z' },
            { timestamp: Date.parse('2026-10-02T12:17:11Z'), offset: '01:48' },
        ],
        [
            'session replay offset text',
            { session_id: 's1', start_time: '02:05', session_start_time: '2026-10-02T12:00:00Z' },
            { timestamp: Date.parse('2026-10-02T12:02:05Z'), offset: '02:05' },
        ],
    ])('opens a recording at the finding from %s', (_, extra, expected) => {
        expect(
            signalDestination(
                signal({ source_product: 'replay_vision', extra: extra as unknown as SignalNodeApi['extra'] })
            )
        ).toEqual({ kind: 'recording', sessionId: 's1', ...expected })
    })

    test.each([
        [
            'an alert investigation',
            signal({
                source_product: 'analytics',
                source_type: 'anomaly_investigation',
                extra: { notebook_short_id: 'nb1' } as unknown as SignalNodeApi['extra'],
            }),
            { kind: 'link', to: '/notebooks/nb1', external: false, label: 'Open investigation' },
        ],
        [
            'a github issue',
            signal({
                source_product: 'github',
                source_type: 'issue',
                extra: { html_url: 'https://github.com/example/web/issues/7' } as unknown as SignalNodeApi['extra'],
            }),
            { kind: 'link', to: 'https://github.com/example/web/issues/7', external: true, label: 'Open issue' },
        ],
        [
            'a scout finding with a thread',
            signal({ content: 'A teammate reported it. Slack thread: https://example.slack.com/archives/C1/p2' }),
            { kind: 'link', to: 'https://example.slack.com/archives/C1/p2', external: true, label: 'Open thread' },
        ],
        [
            'a scout finding with only prose',
            signal({ content: 'A long finding without any link.'.repeat(10) }),
            { kind: 'read' },
        ],
    ])('sends %s to its source', (_, input, expected) => {
        expect(signalDestination(input)).toEqual(expected)
    })

    test.each([
        [
            'an error tracking issue',
            'New error tracking issue created - this particular exception was observed for the first time:\nValueError: `coupon_code`\n\n```\nstack\n```',
            'ValueError: coupon_code',
        ],
        [
            'a support ticket',
            'C: Two weekly invoices show a blank total for annual plans\\. They bill in euros.',
            'Two weekly invoices show a blank total for annual plans.',
        ],
        [
            'long scout prose',
            'The invoice export leaves out the tax column for archived plans. A nightly sync adds it back later.',
            'The invoice export leaves out the tax column for archived plans.',
        ],
        [
            'a github issue cited with a bare link',
            'GitHub issue #4521 (https://github.com/example/shop/issues/4521) reports that `Card was declined. Use another.` shows for `card_error`. It has no PR.',
            'GitHub issue #4521 reports that “Card was declined. Use another.” shows for card_error.',
        ],
        [
            'a long sentence, cut at its last clause',
            'Pressing Apply on the shipping rules settings screen does not keep the new rates, which means every edit to the rates is dropped and the merchant has to write to the help desk about it before the next billing run.',
            'Pressing Apply on the shipping rules settings screen does not keep the new rates, which means every edit to the rates is dropped and the merchant has…',
        ],
        [
            'a long sentence, never cut inside a quotation',
            'In the #shop-support thread about failed payments, one merchant reported that checkouts on the mobile app fail about a third of the time with “Gateway did not answer in time” errors.',
            'In the #shop-support thread about failed payments, one merchant reported that checkouts on the mobile app fail about a third of the time…',
        ],
        [
            'a pganalyze issue',
            '[info] orders-db — #42\nQuery #42 takes 95 ms on average (12345 calls in last 24h)',
            'Query #42 takes 95 ms on average (12,345 calls in last 24h)',
        ],
        [
            'an alert investigation',
            "Anomaly investigation for alert 'Orders dropped' on Orders (verdict: true positive).\nInsight: AB12 / id 1.\nPaid orders fell to 12 in the 09:00 hour on 2026-08-03. The detector fired before.",
            'Paid orders fell to 12 in the 09:00 hour on 3 Aug.',
        ],
        [
            'a scout finding that ends in a thread link',
            'A reviewer said the banner is too loud. Slack reply: https://example.slack.com/archives/C1/p2',
            'A reviewer said the banner is too loud.',
        ],
    ])('writes a headline for %s', (_, content, expected) => {
        expect(signalHeadline(signal({ content }))).toEqual(expected)
    })

    test.each([
        [
            'a support ticket',
            signal({
                source_product: 'conversations',
                extra: { ticket_number: 1042, priority: 'low' } as unknown as SignalNodeApi['extra'],
            }),
            'Ticket #1042',
        ],
        [
            'a github issue',
            signal({
                source_product: 'github',
                source_type: 'issue',
                extra: { number: 7, author_login: 'ada', state: 'open' } as unknown as SignalNodeApi['extra'],
            }),
            'Issue #7',
        ],
        ['a scout finding on a file', signal({ source_id: 'example/web:src/checkout/Address.tsx' }), 'Address.tsx'],
        [
            'a recording',
            signal({
                source_product: 'replay_vision',
                extra: { scanner_name: 'Checkout friction' } as unknown as SignalNodeApi['extra'],
            }),
            '',
        ],
    ])('names only the identifier of %s under its headline', (_, input, expected) => {
        expect(signalMeta(input)).toEqual(expected)
    })

    test.each([
        [
            'an open pull request',
            report({
                pull_requests: [
                    { url: 'https://github.com/example/web/pull/1', state: 'draft', merged: false },
                ] as unknown as SignalReport['pull_requests'],
            }),
            { kind: 'review_pr', state: 'draft', byTask: false },
        ],
        [
            'a task that claimed the report',
            report({
                assignee: {
                    kind: 'task',
                    task_id: 't1',
                    claimed_at: '2026-08-11T09:00:00Z',
                    user: null,
                    agent: null,
                    claim_id: 'c1',
                },
            }),
            { kind: 'task_running', since: '2026-08-11T09:00:00Z' },
        ],
        ['a fix already in flight', report({ already_addressed: true }), { kind: 'already_addressed' }],
        ['a scout waiting for input', report({ status: SignalReportStatus.PENDING_INPUT }), { kind: 'needs_input' }],
        ['an untouched report', report({}), { kind: 'start' }],
    ])('names the next step for %s', (_, input, expected) => {
        expect(todayNextStep(input, { taskRunning: false, slotClaimed: false })).toMatchObject(expected)
    })

    test.each([
        [
            'a bare pull request URL',
            'Fixed in https://github.com/example/web/pull/12, so P2.',
            'Fixed in [#12](https://github.com/example/web/pull/12), so P2.',
        ],
        [
            'a labelled link',
            'See [the PR](https://github.com/example/web/pull/12).',
            'See [the PR](https://github.com/example/web/pull/12).',
        ],
    ])('shortens %s', (_, markdown, expected) => {
        expect(shortenGitHubLinks(markdown)).toEqual(expected)
    })

    test.each([
        ['one pull request', 'Open PR https://github.com/example/web/pull/7 covers it.', '7'],
        [
            'several pull requests',
            'Merged in https://github.com/example/web/pull/7, review https://github.com/example/web/pull/8.',
            null,
        ],
        [
            'several pull requests, one named by the proposal',
            'Lead.\n\n## Problem\n\nMerged in https://github.com/example/web/pull/7.\n\n## Solution\n\nReuse draft https://github.com/example/web/pull/9.',
            '9',
        ],
    ])('names the in-flight pull request for %s', (_, summary, expected) => {
        expect(inFlightPullRequest(report({ summary }))?.number ?? null).toEqual(expected)
    })

    test.each([
        [
            'stops before the limit',
            'First sentence is short. Second sentence is also short. Third one.',
            50,
            'First sentence is short.',
        ],
        [
            'keeps one long sentence',
            'One long sentence that runs past the limit on its own.',
            10,
            'One long sentence that runs past the limit on its own.',
        ],
        [
            'reads list items as sentences',
            '- Reproduce the bug\n- Trace the state',
            60,
            'Reproduce the bug. Trace the state.',
        ],
        [
            'counts a link by the text it shows',
            'Merged in [#12](https://github.com/example/web/pull/12). Land [#13](https://github.com/example/web/pull/13) next.',
            40,
            'Merged in [#12](https://github.com/example/web/pull/12). Land [#13](https://github.com/example/web/pull/13) next.',
        ],
        [
            'closes a bold span it cuts',
            '**The fix is safe. It ships today.** Then measure.',
            20,
            '**The fix is safe.**',
        ],
    ])('keeps text concise when it %s', (_, markdown, maxChars, expected) => {
        expect(conciseText(markdown, maxChars)).toEqual(expected)
    })

    test('shows the newest signal from each source first', () => {
        const signals = [
            signal({ signal_id: 'old-replay', source_product: 'replay_vision', timestamp: '2026-09-01T00:00:00Z' }),
            signal({ signal_id: 'new-replay', source_product: 'replay_vision', timestamp: '2026-09-03T00:00:00Z' }),
            signal({ signal_id: 'scout', source_product: 'signals_scout', timestamp: '2026-08-01T00:00:00Z' }),
        ]
        expect(pickEvidence(signals, 2).map((picked) => picked.signal_id)).toEqual(['new-replay', 'scout'])
    })

    test('shows one row for several checks of the same alert', () => {
        const check = (id: string, timestamp: string): SignalNodeApi =>
            signal({
                signal_id: id,
                source_product: 'analytics',
                source_id: id,
                timestamp,
                extra: { alert_id: 'orders-alert' } as unknown as SignalNodeApi['extra'],
            })
        const signals = [check('early-check', '2026-09-01T09:00:00Z'), check('late-check', '2026-09-01T09:40:00Z')]
        expect(pickEvidence(signals, 3).map((picked) => picked.signal_id)).toEqual(['late-check'])
    })

    test.each([
        [
            'counts with units',
            'Crashing across 41 teams, 2,316 people and 120–150 users a week.',
            ['41', '2,316', '120–150'],
        ],
        ['not times, dates, versions or years', 'At 07:00 on 2026-08-12 an SDK-5.6 build failed in 2026.', []],
        ['not the time window of a claim', 'In the trailing 14 days 63 people waited 9 minutes.', ['63', '9 minutes']],
        ['not a day of the month', 'Over the 30 days to 1 Sep, 4,512 orders failed.', ['4,512']],
        ['amounts of money', 'About $4.2K in spend and €40 a seat, filed as #123 on $pageview.', ['$4.2K', '€40']],
    ])('finds figures in %s', (_, text, expected) => {
        expect(findFigures(text).map((figure) => figure.text)).toEqual(expected)
    })

    test.each([
        [
            'an older quote',
            '2026-09-04T10:00:00Z',
            'A session from today hit it.',
            'A session from today [4 Sep] hit it.',
        ],
        ['a quote from today', '2026-10-03T08:00:00Z', 'A session from today hit it.', 'A session from today hit it.'],
    ])('dates "today" in %s', (_, date, text, expected) => {
        expect(anchorToday(text, date, dayjs('2026-10-03T12:00:00Z'))).toEqual(expected)
    })

    test.each([
        [
            'a pganalyze issue, without its header line',
            signal({
                source_product: 'pganalyze',
                source_type: 'issue',
                content: '[info] orders-db — #42\nQuery #42 takes 95 ms on average (12345 calls in last 24h)',
                extra: { server_name: 'orders-db', severity: 'info' } as SignalNodeApi['extra'],
            }),
            {
                lead: 'Query #42 takes 95 ms on average (12,345 calls in last 24h)',
                rest: '',
                facts: ['orders-db', 'info severity'],
            },
        ],
        [
            'a scout finding that cites a Slack thread, without the sentence that only points at it',
            signal({
                content:
                    'The August 12 #shop-support discussion counted 2,316 merchants using saved carts over 30 days. Most were on the annual plan. The thread is available at https://example.slack.com/archives/C1/p2.',
                extra: { skill_name: 'signals-scout-shop-support' } as SignalNodeApi['extra'],
            }),
            {
                lead: 'The August 12 #shop-support discussion counted 2,316 merchants using saved carts over 30 days.',
                rest: 'Most were on the annual plan.',
                facts: ['Shop support scout'],
            },
        ],
        [
            'a scout finding, split into its lead and the rest',
            signal({
                content:
                    'The 14-message thread records a recurring gap in the order history page. The discussion proposes a date filter.',
                extra: { skill_name: 'signals-scout-shop-support' } as SignalNodeApi['extra'],
            }),
            {
                lead: 'The 14-message thread records a recurring gap in the order history page.',
                rest: 'The discussion proposes a date filter.',
                facts: ['Shop support scout'],
            },
        ],
    ])('opens %s', (_, item, expected) => {
        expect(signalReading(item)).toEqual(expected)
    })

    test('picks the lines a finding quotes and marks the quoted code', () => {
        const file = [
            "import { useValues } from 'kea'",
            '',
            'export function CartRow({ productId }: Props): JSX.Element {',
            '    const { prices } = useValues(pricesLogic)',
            '    const price = prices[productId]',
            '    return <Price price={price} />',
            '}',
        ].join('\n')
        const identifiers = codeIdentifiers(
            '`CartRow.tsx` calls `useValues` on the store-wide logic and reads `prices[productId]` afterward.'
        )
        expect(identifiers).toEqual(['useValues', 'prices[productId]'])
        expect(codeExcerpt(file, identifiers)).toEqual({
            startLine: 3,
            lines: [
                'export function CartRow({ productId }: Props): JSX.Element {',
                '    const { prices } = useValues(pricesLogic)',
                '    const price = prices[productId]',
                '    return <Price price={price} />',
                '}',
            ],
            marks: [
                { line: 1, start: 23, end: 32 },
                { line: 2, start: 18, end: 35 },
            ],
        })
    })

    test.each([
        [
            'each backing number once and never a day of the month',
            '4 failures on 2 Aug, 12 on 12 Aug, and 31 on 14 Aug.',
            ['4', '12', '31'],
            ['4', '12', '31'],
        ],
        ['an amount of money with its currency sign', 'About $4.2K in seven-day spend.', ['4.2'], ['$4.2K']],
    ])('emphasizes %s', (_, text, values, expected) => {
        const segments = highlightSegments(text, values)
        expect(segments.filter((segment) => segment.marked).map((segment) => segment.text)).toEqual(expected)
        expect(segments.map((segment) => segment.text).join('')).toEqual(text)
    })

    test.each([
        ['signals-scout-checkout-github-issues', 'Checkout GitHub issues scout'],
        ['signals-scout-react-render', 'React render scout'],
    ])('names the scout for skill %s', (skill, expected) => {
        expect(scoutLabel(skill)).toEqual(expected)
    })

    test('marks counts of people before other figures', () => {
        const figures = findFigures(
            'We logged 212 failed requests across 57 people and showed it 33 times to 18 people.'
        )
        expect([...figuresToMark(figures, 3)].map((figure) => figure.text)).toEqual(['57', '18', '212'])
    })

    test.each([
        [
            'the signal that states the figure',
            { text: '2,316', value: '2,316', noun: 'people' },
            [signal({ signal_id: 'carts', content: 'Saved carts were opened by 2316 people in 30 days.' })],
            [],
            { kind: 'signal', excerpt: 'Saved carts were opened by 2,316 people in 30 days.', parts: null },
        ],
        [
            'a small figure only when its noun matches',
            { text: '14', value: '14', noun: 'days' },
            [signal({ content: 'Retries happened 14 times today.' })],
            [],
            null,
        ],
        [
            'the newest research that states the figure',
            { text: '18', value: '18', noun: 'people' },
            [],
            [
                {
                    type: 'priority_judgment',
                    created_at: '2026-10-02T00:00:00Z',
                    content: { explanation: 'The empty cart page was shown to 18 people.' },
                },
                {
                    type: 'priority_judgment',
                    created_at: '2026-09-01T00:00:00Z',
                    content: { explanation: 'The empty cart page was shown to 18 people last month.' },
                },
            ],
            { kind: 'research', excerpt: 'The empty cart page was shown to 18 people.', parts: null },
        ],
        [
            'a total the research gives as parts',
            { text: '212', value: '212', noun: 'failed' },
            [],
            [
                {
                    type: 'priority_judgment',
                    created_at: '2026-10-02T00:00:00Z',
                    content: { explanation: 'Failed checkout requests rose to 150 timeout and 62 declined.' },
                },
            ],
            {
                kind: 'research',
                excerpt: 'Failed checkout requests rose to 150 timeout and 62 declined.',
                parts: ['150', '62'],
            },
        ],
    ])('traces %s', (_, figure, signals, artefacts, expected) => {
        const source = figureSource(figure, {
            signals,
            research: researchNotes(artefacts),
            summary: null,
            shownText: 'We logged 212 failed checkout requests, shown to 18 people.',
        })
        expect(source ? { kind: source.kind, excerpt: source.excerpt, parts: source.parts } : null).toEqual(expected)
    })

    test('splits inline markdown into text, code, bold and links', () => {
        expect(inlineSegments('Run `retrieve` for **41 teams**, see [#12](https://github.com/x/y/pull/12).')).toEqual([
            { kind: 'text', text: 'Run ' },
            { kind: 'code', text: 'retrieve' },
            { kind: 'text', text: ' for ' },
            { kind: 'strong', text: '41 teams' },
            { kind: 'text', text: ', see ' },
            { kind: 'link', text: '#12', href: 'https://github.com/x/y/pull/12' },
            { kind: 'text', text: '.' },
        ])
    })

    test.each([
        [
            'implement for a ready, actionable report',
            { actionability: 'immediately_actionable', status: 'ready' },
            'implement',
        ],
        [
            'investigate when it needs a person',
            { actionability: 'requires_human_input', status: 'pending_input' },
            'investigate',
        ],
    ])('chooses %s', (_, report, expected) => {
        expect(reportWorkKind(report as never)).toEqual(expected)
    })

    test.each([
        [
            'starts at the first day with a value',
            { series: [0, 0, 3, 5], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'day' } } },
            { data: [3, 5], since: '30 Sep', start: '2026-09-30' },
        ],
        [
            'keeps the whole window when it is not daily',
            { series: [0, 2, 3], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'week' } } },
            { data: [0, 2, 3], since: null, start: null },
        ],
    ])('builds a daily trend that %s', (_, metric, expected) => {
        expect(dailyTrend(metric as never)).toEqual(expected)
    })
})
