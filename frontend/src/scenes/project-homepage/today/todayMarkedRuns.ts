import type { KeyClauseApi } from 'products/today/frontend/generated/api.schemas'

import type { TodayMarkedFigure } from './todayFigureSources'
import { inlineSegments } from './todayProse'

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

function clauseCuts(length: number, offset: number, keyClauses: KeyClauseApi[]): number[] {
    return keyClauses
        .flatMap((keyClause) => [keyClause.start - offset, keyClause.end - offset])
        .filter((point) => point > 0 && point < length)
}

function sortedPoints(length: number, cuts: number[]): number[] {
    return [...new Set([0, length, ...cuts])].sort((first, second) => first - second)
}

function splitPieces(
    text: string,
    segment: number,
    offset: number,
    keyClauses: KeyClauseApi[],
    piece: (key: string, text: string) => TodayMarkedPiece
): PlacedPiece[] {
    const points = sortedPoints(text.length, clauseCuts(text.length, offset, keyClauses))
    return points.slice(0, -1).map((from, index) => {
        const to = points[index + 1]
        return { piece: piece(`${segment}-${from}`, text.slice(from, to)), from: offset + from, to: offset + to }
    })
}

function textPieces(
    text: string,
    segment: number,
    offset: number,
    figures: TodayMarkedFigure[],
    keyClauses: KeyClauseApi[]
): PlacedPiece[] {
    const own = figures.filter((figure) => figure.segment === segment)
    const insideFigure = (point: number): boolean => own.some((figure) => point > figure.start && point < figure.end)
    const cuts = clauseCuts(text.length, offset, keyClauses).filter((point) => !insideFigure(point))
    const points = sortedPoints(text.length, [...own.flatMap((figure) => [figure.start, figure.end]), ...cuts])
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

function placedPieces(markdown: string, figures: TodayMarkedFigure[], keyClauses: KeyClauseApi[]): PlacedPiece[] {
    let offset = 0
    return inlineSegments(markdown).flatMap((segment, index) => {
        const from = offset
        offset += segment.text.length
        switch (segment.kind) {
            case 'code':
                return splitPieces(segment.text, index, from, keyClauses, (key, text) => ({ kind: 'code', key, text }))
            case 'link':
                return splitPieces(segment.text, index, from, keyClauses, (key, text) => ({
                    kind: 'link',
                    key,
                    text,
                    href: segment.href,
                }))
            default:
                return textPieces(segment.text, index, from, figures, keyClauses)
        }
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
