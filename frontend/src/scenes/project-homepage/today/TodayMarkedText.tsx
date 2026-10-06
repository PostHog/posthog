import { Fragment } from 'react'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { KeyClauseApi } from 'products/today/frontend/generated/api.schemas'

import { TodayFigureMark } from './TodayFigureMark'
import type { TodayMarkedFigure } from './todayFigureSources'
import { TodayKeyClauseMark } from './TodayKeyClauseMark'
import { TodayMarkedPiece, markedRuns } from './todayMarkedRuns'

function MarkedPiece({ piece, reportId }: { piece: TodayMarkedPiece; reportId: string }): JSX.Element {
    switch (piece.kind) {
        case 'code':
            return <code className="text-[0.9em]">{piece.text}</code>
        case 'link':
            return (
                <LinkPrimitive to={piece.href} target="_blank" className="underline underline-offset-2">
                    {piece.text}
                </LinkPrimitive>
            )
        case 'figure':
            return (
                <TodayFigureMark
                    figure={piece.figure.text}
                    content={piece.figure.content}
                    reportId={reportId}
                    order={piece.order}
                    kind="figure"
                >
                    {piece.figure.text}
                </TodayFigureMark>
            )
        default:
            return <span>{piece.text}</span>
    }
}

export function TodayMarkedText({
    markdown,
    marked,
    keyClauses,
    reportId,
}: {
    markdown: string
    marked: TodayMarkedFigure[]
    keyClauses: KeyClauseApi[]
    reportId: string
}): JSX.Element {
    const runs = markedRuns(markdown, marked, keyClauses)
    return (
        <>
            {runs.map(({ keyClause, pieces }) => {
                const content = pieces.map((piece) => <MarkedPiece key={piece.key} piece={piece} reportId={reportId} />)
                return keyClause ? (
                    <TodayKeyClauseMark key={pieces[0].key} keyClause={keyClause} reportId={reportId}>
                        {content}
                    </TodayKeyClauseMark>
                ) : (
                    <Fragment key={pieces[0].key}>{content}</Fragment>
                )
            })}
        </>
    )
}
