import type { KeyClauseApi, KeyClauseRoleEnumApi } from 'products/today/frontend/generated/api.schemas'

import type { TodayMarkedFigure } from './todayFigureSources'
import { TodayMarkedPiece, markedRuns } from './todayMarkedRuns'
import { renderedText } from './todayProse'

function figureIn(markdown: string, text: string): TodayMarkedFigure {
    const start = renderedText(markdown).indexOf(text)
    return { start, end: start + text.length, text, content: { kind: 'none' } }
}

function keyClausesIn(markdown: string, picks: [KeyClauseRoleEnumApi, string][]): KeyClauseApi[] {
    const shown = renderedText(markdown)
    return picks.map(([role, text]) => ({
        start: shown.indexOf(text),
        end: shown.indexOf(text) + text.length,
        role,
        expansion: ['The report explains it.'],
    }))
}

function described(piece: TodayMarkedPiece): [string, string] {
    if (piece.kind === 'figure') {
        return ['figure', piece.figure.text]
    }
    return [piece.kind, piece.text]
}

describe('todayMarkedRuns', () => {
    test.each([
        [
            'a figure, code and a link inside key clauses',
            'Shoppers in 41 teams see an empty cart because `syncCart` drops the [session token](https://example.com/token).',
            [
                ['problem', 'Shoppers in 41 teams see an empty cart'],
                ['cause', 'because syncCart drops the session token'],
            ] as [KeyClauseRoleEnumApi, string][],
            [
                ['problem', [['text', 'Shoppers in ']]],
                [null, [['figure', '41']]],
                ['problem', [['text', ' teams see an empty cart']]],
                [null, [['text', ' ']]],
                [
                    'cause',
                    [
                        ['text', 'because '],
                        ['code', 'syncCart'],
                        ['text', ' drops the '],
                        ['link', 'session token'],
                    ],
                ],
                [null, [['text', '.']]],
            ],
        ],
        [
            'a key clause that starts inside code',
            'Payments fail for 41 teams in `retryCart because the queue stalls` at peak.',
            [['cause', 'because the queue stalls at peak']] as [KeyClauseRoleEnumApi, string][],
            [
                [
                    null,
                    [
                        ['text', 'Payments fail for '],
                        ['figure', '41'],
                        ['text', ' teams in '],
                        ['code', 'retryCart '],
                    ],
                ],
                [
                    'cause',
                    [
                        ['code', 'because the queue stalls'],
                        ['text', ' at peak'],
                    ],
                ],
                [null, [['text', '.']]],
            ],
        ],
    ])('places the pieces of %s', (_, markdown, picks, expected) => {
        const keyClauses = keyClausesIn(markdown, picks)
        const runs = markedRuns(markdown, [figureIn(markdown, '41')], keyClauses)
        expect(runs.map((run) => [run.keyClause?.role ?? null, run.pieces.map(described)])).toEqual(expected)
    })
})
