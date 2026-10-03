import { Fragment } from 'react'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayFigureMark } from './TodayFigureMark'
import { TodayKeyClauseMark } from './TodayKeyClauseMark'
import type { TodayKeyClause } from './todayKeyClauses'
import { TodayMarkedFigure, inlineSegments } from './todayReportPresentation'

interface Piece {
    key: string
    node: JSX.Element
    keyClause: TodayKeyClause | null
}

const NO_KEY_CLAUSES: TodayKeyClause[] = []

function groupKeyClauses(pieces: Piece[], reportId: string): JSX.Element[] {
    const out: JSX.Element[] = []
    let run: Piece[] = []
    const flush = (): void => {
        const keyClause = run[0]?.keyClause
        if (keyClause) {
            out.push(
                <TodayKeyClauseMark key={`c${run[0].key}`} keyClause={keyClause} reportId={reportId}>
                    {run.map((piece) => piece.node)}
                </TodayKeyClauseMark>
            )
        }
        run = []
    }
    for (const piece of pieces) {
        if (piece.keyClause && piece.keyClause === run[0]?.keyClause) {
            run.push(piece)
        } else {
            flush()
            if (piece.keyClause) {
                run.push(piece)
            } else {
                out.push(piece.node)
            }
        }
    }
    flush()
    return out
}

export function TodayMarkedText({
    markdown,
    marked,
    reportId,
    keyClauses = NO_KEY_CLAUSES,
}: {
    markdown: string
    marked: TodayMarkedFigure[]
    reportId: string
    keyClauses?: TodayKeyClause[]
}): JSX.Element {
    const coveringClause = (from: number, to: number): TodayKeyClause | null =>
        keyClauses.find((clause) => from >= clause.start && to <= clause.end) ?? null

    const textPieces = (text: string, segment: number, offset: number): Piece[] => {
        const figures = marked.filter((candidate) => candidate.segment === segment)
        const insideFigure = (point: number): boolean =>
            figures.some((figure) => point > figure.start && point < figure.end)
        const cuts = new Set([0, text.length, ...figures.flatMap((figure) => [figure.start, figure.end])])
        for (const point of keyClauses.flatMap((clause) => [clause.start - offset, clause.end - offset])) {
            if (point > 0 && point < text.length && !insideFigure(point)) {
                cuts.add(point)
            }
        }
        const points = [...cuts].sort((first, second) => first - second)
        return points.slice(0, -1).map((from, index) => {
            const to = points[index + 1]
            const figure = figures.find((candidate) => candidate.start === from)
            const key = `${segment}-${from}`
            return {
                key,
                keyClause: coveringClause(offset + from, offset + to),
                node: figure ? (
                    <TodayFigureMark
                        key={key}
                        figure={figure.text}
                        content={figure.content}
                        reportId={reportId}
                        order={marked.indexOf(figure)}
                    >
                        {figure.text}
                    </TodayFigureMark>
                ) : (
                    <span key={key}>{text.slice(from, to)}</span>
                ),
            }
        })
    }

    let offset = 0
    const pieces = inlineSegments(markdown).flatMap((segment, index): Piece[] => {
        const start = offset
        offset += segment.text.length
        const key = `${index}`
        switch (segment.kind) {
            case 'code':
                return [
                    {
                        key,
                        keyClause: coveringClause(start, offset),
                        node: (
                            <code key={key} className="text-[0.9em]">
                                {segment.text}
                            </code>
                        ),
                    },
                ]
            case 'link':
                return [
                    {
                        key,
                        keyClause: coveringClause(start, offset),
                        node: (
                            <LinkPrimitive
                                key={key}
                                to={segment.href}
                                target="_blank"
                                className="underline underline-offset-2"
                            >
                                {segment.text}
                            </LinkPrimitive>
                        ),
                    },
                ]
            default:
                return textPieces(segment.text, index, start)
        }
    })

    return <Fragment>{groupKeyClauses(pieces, reportId)}</Fragment>
}
