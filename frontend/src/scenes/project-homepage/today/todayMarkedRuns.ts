import type { TodayMarkedFigure } from './todayFigureSources'
import type { TodayKeyClause } from './todayKeyClauses'
import { inlineSegments } from './todayProse'

export type TodayMarkedPiece =
    | { kind: 'text' | 'code'; key: string; text: string }
    | { kind: 'link'; key: string; text: string; href: string }
    | { kind: 'figure'; key: string; figure: TodayMarkedFigure; order: number }

interface TodayMarkedRun {
    keyClause: TodayKeyClause | null
    pieces: TodayMarkedPiece[]
}

interface PlacedPiece {
    piece: TodayMarkedPiece
    from: number
    to: number
}

function textPieces(
    text: string,
    segment: number,
    offset: number,
    figures: TodayMarkedFigure[],
    keyClauses: TodayKeyClause[]
): PlacedPiece[] {
    const own = figures.filter((figure) => figure.segment === segment)
    const insideFigure = (point: number): boolean => own.some((figure) => point > figure.start && point < figure.end)
    const clauseCuts = keyClauses
        .flatMap((keyClause) => [keyClause.start - offset, keyClause.end - offset])
        .filter((point) => point > 0 && point < text.length && !insideFigure(point))
    const cuts = [...new Set([0, text.length, ...own.flatMap((figure) => [figure.start, figure.end]), ...clauseCuts])]
    const points = cuts.sort((first, second) => first - second)
    return points.slice(0, -1).map((from, index) => {
        const to = points[index + 1]
        const figure = own.find((candidate) => candidate.start === from)
        const key = `${segment}-${from}`
        const piece: TodayMarkedPiece = figure
            ? { kind: 'figure', key, figure, order: figures.indexOf(figure) }
            : { kind: 'text', key, text: text.slice(from, to) }
        return { piece, from: offset + from, to: offset + to }
    })
}

function placedPieces(markdown: string, figures: TodayMarkedFigure[], keyClauses: TodayKeyClause[]): PlacedPiece[] {
    let offset = 0
    return inlineSegments(markdown).flatMap((segment, index) => {
        const from = offset
        offset += segment.text.length
        const key = `${index}`
        switch (segment.kind) {
            case 'code':
                return [{ piece: { kind: 'code', key, text: segment.text }, from, to: offset }]
            case 'link':
                return [{ piece: { kind: 'link', key, text: segment.text, href: segment.href }, from, to: offset }]
            default:
                return textPieces(segment.text, index, from, figures, keyClauses)
        }
    })
}

export function markedRuns(
    markdown: string,
    figures: TodayMarkedFigure[],
    keyClauses: TodayKeyClause[]
): TodayMarkedRun[] {
    const runs: TodayMarkedRun[] = []
    for (const { piece, from, to } of placedPieces(markdown, figures, keyClauses)) {
        const keyClause = keyClauses.find((candidate) => from >= candidate.start && to <= candidate.end) ?? null
        const last = runs[runs.length - 1]
        if (last && last.keyClause === keyClause) {
            last.pieces.push(piece)
        } else {
            runs.push({ keyClause, pieces: [piece] })
        }
    }
    return runs
}
