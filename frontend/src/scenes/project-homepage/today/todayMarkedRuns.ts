import type { KeyClauseApi } from 'products/today/frontend/generated/api.schemas'

import type { TodayMarkedFigure } from './todayFigureSources'
import { type TodayInlineSegment, inlineSegments } from './todayProse'

export type TodayMarkedPiece =
    | { kind: 'text' | 'code'; key: string; text: string }
    | { kind: 'link'; key: string; text: string; href: string }
    | { kind: 'figure'; key: string; figure: TodayMarkedFigure; order: number }

interface TodayMarkedRun {
    keyClause: KeyClauseApi | null
    pieces: TodayMarkedPiece[]
}

interface PlacedPiece {
    piece: TodayMarkedPiece
    from: number
    to: number
}

function segmentPieces(
    segment: TodayInlineSegment,
    index: number,
    from: number,
    figures: TodayMarkedFigure[],
    keyClauses: KeyClauseApi[]
): PlacedPiece[] {
    const to = from + segment.text.length
    const own = segment.kind === 'text' ? figures.filter((figure) => from <= figure.start && figure.end <= to) : []
    const insideFigure = (point: number): boolean => own.some((figure) => point > figure.start && point < figure.end)
    const cuts = [
        ...own.flatMap((figure) => [figure.start, figure.end]),
        ...keyClauses.flatMap((keyClause) => [keyClause.start, keyClause.end]).filter((point) => !insideFigure(point)),
    ].filter((point) => point > from && point < to)
    const points = [...new Set([from, to, ...cuts])].sort((first, second) => first - second)
    return points.slice(0, -1).map((start, position) => {
        const end = points[position + 1]
        const key = `${index}-${start - from}`
        const text = segment.text.slice(start - from, end - from)
        const figure = own.find((candidate) => candidate.start === start)
        const piece: TodayMarkedPiece = figure
            ? { kind: 'figure', key, figure, order: figures.indexOf(figure) }
            : segment.kind === 'link'
              ? { kind: 'link', key, text, href: segment.href }
              : { kind: segment.kind, key, text }
        return { piece, from: start, to: end }
    })
}

function placedPieces(markdown: string, figures: TodayMarkedFigure[], keyClauses: KeyClauseApi[]): PlacedPiece[] {
    let offset = 0
    return inlineSegments(markdown).flatMap((segment, index) => {
        const from = offset
        offset += segment.text.length
        return segmentPieces(segment, index, from, figures, keyClauses)
    })
}

export function markedRuns(
    markdown: string,
    figures: TodayMarkedFigure[],
    keyClauses: KeyClauseApi[]
): TodayMarkedRun[] {
    const runs: TodayMarkedRun[] = []
    for (const { piece, from, to } of placedPieces(markdown, figures, keyClauses)) {
        const keyClause =
            piece.kind === 'figure'
                ? null
                : (keyClauses.find((candidate) => from >= candidate.start && to <= candidate.end) ?? null)
        const last = runs[runs.length - 1]
        if (last && last.keyClause === keyClause) {
            last.pieces.push(piece)
        } else {
            runs.push({ keyClause, pieces: [piece] })
        }
    }
    return runs
}
