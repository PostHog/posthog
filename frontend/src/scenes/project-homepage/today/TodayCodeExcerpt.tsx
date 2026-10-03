import { IconExternal } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayPenStroke } from './TodayPenStroke'
import { TodayCodeExcerpt as Excerpt, TodayCodeFile } from './todayReportPresentation'
import { TodayChosenExcerpt } from './todaySignalPreview'

const PEN_DELAY_MS = 120
const PEN_STAGGER_MS = 120

function indentOf(line: string): number {
    return line.length - line.trimStart().length
}

function CodeLine({ text, marks, order }: { text: string; marks: Excerpt['marks']; order: number }): JSX.Element {
    const parts: JSX.Element[] = []
    let last = 0
    marks.forEach((mark, index) => {
        if (mark.start < last) {
            return
        }
        parts.push(<span key={`t${index}`}>{text.slice(last, mark.start)}</span>)
        parts.push(
            <span key={`m${index}`} className="TodayPenned text-[var(--foreground)]">
                {text.slice(mark.start, mark.end)}
                <TodayPenStroke
                    seed={`${text}${mark.start}`}
                    delayMs={PEN_DELAY_MS + (order + index) * PEN_STAGGER_MS}
                />
            </span>
        )
        last = mark.end
    })
    parts.push(<span key="rest">{text.slice(last)}</span>)
    return <>{parts}</>
}

/** A few lines of the file a finding is about, read from the team's repository, with the quoted code marked. */
export function TodayCodeExcerpt({
    file,
    chosen,
}: {
    file: TodayCodeFile
    chosen: TodayChosenExcerpt | 'loading'
}): JSX.Element {
    const shown = chosen === 'loading' ? file : chosen.file
    const directory = shown.path.includes('/') ? `${shown.path.slice(0, shown.path.lastIndexOf('/') + 1)}` : ''
    const name = shown.path.slice(directory.length)
    const excerpt = chosen === 'loading' ? null : chosen.excerpt
    const lastLine = excerpt ? excerpt.startLine + excerpt.lines.length - 1 : null

    return (
        <figure className="TodayCode m-0 overflow-hidden rounded-md border" data-attr="today-report-code-excerpt">
            <figcaption className="TodayCode__header flex items-center justify-between gap-3 px-3 py-1.5">
                <Text
                    size="xs"
                    variant="muted"
                    render={<span />}
                    className="flex min-w-0 items-baseline font-mono"
                    title={shown.path}
                >
                    <span className="min-w-0 truncate">{directory}</span>
                    <span className="shrink-0 text-[var(--foreground)]">{name}</span>
                    {excerpt && (
                        <span className="shrink-0 ps-2 tabular-nums">
                            L{excerpt.startLine}–{lastLine}
                        </span>
                    )}
                </Text>
                {chosen !== 'loading' && excerpt && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-me-2 shrink-0 px-2"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to={`${chosen.read.url}#L${excerpt.startLine}-L${lastLine}`}
                                target="_blank"
                            />
                        }
                        data-attr="today-report-code-github"
                    >
                        Open on GitHub
                        <IconExternal />
                    </Button>
                )}
            </figcaption>
            {excerpt ? (
                <pre className="TodayCode__body m-0 py-2 font-mono text-xs leading-relaxed">
                    {excerpt.lines.map((line, index) => (
                        <div key={index} className="flex">
                            <span
                                aria-hidden
                                className="w-12 shrink-0 select-none pe-3 text-right text-muted-foreground tabular-nums"
                            >
                                {excerpt.startLine + index}
                            </span>
                            <code className="flex min-w-0 pe-3">
                                <span className="shrink-0 whitespace-pre">{line.slice(0, indentOf(line))}</span>
                                <span className="TodayCode__line min-w-0 break-words whitespace-pre-wrap">
                                    <CodeLine
                                        text={line.slice(indentOf(line))}
                                        marks={excerpt.marks
                                            .filter((mark) => mark.line === index)
                                            .map((mark) => ({
                                                ...mark,
                                                start: mark.start - indentOf(line),
                                                end: mark.end - indentOf(line),
                                            }))}
                                        order={index}
                                    />
                                </span>
                            </code>
                        </div>
                    ))}
                </pre>
            ) : (
                <div className="flex flex-col gap-2 px-3 py-3">
                    <Skeleton className="h-3 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                    <Skeleton className="h-3 w-2/3" />
                </div>
            )}
        </figure>
    )
}
