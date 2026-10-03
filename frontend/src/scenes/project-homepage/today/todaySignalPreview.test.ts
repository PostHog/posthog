import type { RepositoryFileApi } from 'products/business_knowledge/frontend/generated/api.schemas'
import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { codeExcerpt, codeExcerptCandidates } from './todayReportPresentation'
import { bodyParagraph, chooseCodeExcerpt, codeSiblingFiles, exceptionChain, signalPreview } from './todaySignalPreview'

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

function read(path: string, lines: string[]): RepositoryFileApi {
    return { content: lines.join('\n'), url: `https://github.com/acme/app/blob/abc/${path}` } as RepositoryFileApi
}

const OWN = { repo: 'acme/app', path: 'src/cards/Cards.tsx' }
const SIBLING = { repo: 'acme/app', path: 'src/cards/cardsLogic.ts' }
const OWN_READ = read(OWN.path, ['export function Cards(): JSX.Element {', '    return <List />', '}'])
const SIBLING_READ = read(SIBLING.path, ['const PAGE_SIZE = 50', 'export const CARDS_MAX = 120'])

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
        ['the sibling file that holds the quote', [OWN_READ, SIBLING_READ], 'cardsLogic.ts'],
        ['loading while a file is still being read', [OWN_READ, 'loading' as const], 'loading'],
        ['nothing when no file holds the quote', [OWN_READ, null], null],
    ])('chooses %s', (_, reads, expected) => {
        const chosen = chooseCodeExcerpt([OWN, SIBLING], reads, ['CARDS_MAX = 120'])
        expect(chosen && chosen !== 'loading' ? chosen.file.path.split('/').pop() : chosen).toEqual(expected)
    })

    test('finds the files a finding names in its own folder', () => {
        expect(codeSiblingFiles(OWN, '`Cards.tsx` maps cards, and `cardsLogic.ts` caps them at `CARDS_MAX`.')).toEqual([
            SIBLING,
        ])
    })

    test('shows the lines that hold the most distinct pieces of the quoted code', () => {
        const gap = Array(9).fill('')
        const file = [
            'const a = rareName',
            ...gap,
            'one(commonName, otherName)',
            ...gap,
            'two(commonName)',
            ...gap,
            'three(otherName)',
        ].join('\n')
        expect(codeExcerpt(file, ['rareName', 'commonName', 'otherName'])?.startLine).toEqual(11)
    })

    test('offers each separate place that holds most of the quoted code', () => {
        const file = [
            'actions({',
            '    addItem: (id: string) => ({ id }),',
            '    removeItem: (id: string) => ({ id }),',
            '}),',
            ...Array(6).fill(''),
            'reducers({',
            '    items: [',
            '        {},',
            '        {',
            '            addItem: (state, { id }) => ({ ...state, [id]: true }),',
            '            removeItem: (state, { id }) => ({ ...state, [id]: false }),',
        ].join('\n')
        expect(
            codeExcerptCandidates(file, ['items', 'addItem', 'removeItem']).map((excerpt) => excerpt.startLine)
        ).toEqual([11, 1])
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
            signal({ content: 'A teammate said the banner is too loud. https://acme.slack.com/archives/C1/p1' }),
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
                    html_url: 'https://github.com/acme/app/issues/7',
                    number: 7,
                    state: 'open',
                } as SignalNodeApi['extra'],
            }),
            expect.objectContaining({
                hint: 'Show the description',
                text: 'The cart forgets the coupon code after a refresh.',
                open: { to: 'https://github.com/acme/app/issues/7', external: true, label: 'Open on GitHub' },
            }),
        ],
    ])('previews %s', (_, item, expected) => {
        expect(signalPreview(item)).toEqual(expected)
    })
})
