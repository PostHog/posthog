import { findFigures } from './todayFigures'
import type { TodayMarkedFigure } from './todayFigureSources'
import { TodayClauseRole, TodayKeyClause, textClauses } from './todayKeyClauses'
import { TodayMarkedPiece, markedRuns } from './todayMarkedRuns'
import { inlineSegments, renderedText } from './todayProse'

function figuresIn(markdown: string): TodayMarkedFigure[] {
    return inlineSegments(markdown).flatMap((segment, index) =>
        segment.kind === 'text'
            ? findFigures(segment.text).map((figure) => ({ ...figure, segment: index, content: { kind: 'none' } }))
            : []
    )
}

function keyClausesIn(markdown: string, picks: [TodayClauseRole, string][]): TodayKeyClause[] {
    const clauses = textClauses(renderedText(markdown))
    return picks.flatMap(([role, text]) =>
        clauses
            .filter((clause) => clause.text === text)
            .map((clause) => ({ ...clause, role, confidence: 0.9, expansion: ['The report explains it.'] }))
    )
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
            ] as [TodayClauseRole, string][],
            [
                [
                    'problem',
                    [
                        ['text', 'Shoppers in '],
                        ['figure', '41'],
                        ['text', ' teams see an empty cart'],
                    ],
                ],
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
    ])('keeps pieces whole for %s', (_, markdown, picks, expected) => {
        const keyClauses = keyClausesIn(markdown, picks)
        expect(keyClauses.map((keyClause) => keyClause.text)).toEqual(picks.map(([, text]) => text))
        const runs = markedRuns(markdown, figuresIn(markdown), keyClauses)
        expect(runs.map((run) => [run.keyClause?.role ?? null, run.pieces.map(described)])).toEqual(expected)
    })
})
