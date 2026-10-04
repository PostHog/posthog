import { IconExternal } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { CodeFileApi } from 'products/today/frontend/generated/api.schemas'

import { TodayPenMark } from './TodayPenMark'
import type { TodayCodeQuote, TodayCodeWindow } from './todayQuotedCode'

const PEN_DELAY_MS = 120
const PEN_STAGGER_MS = 120

function CodeLine({
    line,
    marks,
    order,
}: {
    line: string
    marks: TodayCodeWindow['marks']
    order: number
}): JSX.Element {
    const indent = line.length - line.trimStart().length
    const parts: JSX.Element[] = []
    let last = indent
    marks.forEach((mark, index) => {
        if (mark.start < last) {
            return
        }
        parts.push(<span key={`t${index}`}>{line.slice(last, mark.start)}</span>)
        parts.push(
            <TodayPenMark
                key={`m${index}`}
                seed={`${line}${mark.start}`}
                delayMs={PEN_DELAY_MS + (order + index) * PEN_STAGGER_MS}
            >
                {line.slice(mark.start, mark.end)}
            </TodayPenMark>
        )
        last = mark.end
    })
    parts.push(<span key="rest">{line.slice(last)}</span>)
    return (
        <code className="flex min-w-0 pe-3">
            <span className="shrink-0 whitespace-pre">{line.slice(0, indent)}</span>
            <span className="TodayCodeExcerpt__line min-w-0 break-words whitespace-pre-wrap">{parts}</span>
        </code>
    )
}

export function TodayCodeExcerpt({
    file,
    quote,
}: {
    file: CodeFileApi
    quote: TodayCodeQuote | 'loading'
}): JSX.Element {
    const loaded = quote === 'loading' ? null : quote
    const shown = loaded?.file ?? file
    const folderEnd = shown.path.lastIndexOf('/') + 1
    const directory = shown.path.slice(0, folderEnd)
    const name = shown.path.slice(folderEnd)
    const excerpt = loaded?.excerpt ?? null
    const lastLine = excerpt ? excerpt.startLine + excerpt.lines.length - 1 : null
    const githubUrl = loaded ? `${loaded.read.url}#L${loaded.excerpt.startLine}-L${lastLine}` : null

    return (
        <figure
            className="TodayCodeExcerpt m-0 overflow-hidden rounded-md border"
            data-attr="today-report-code-excerpt"
        >
            <figcaption className="TodayCodeExcerpt__header flex items-center justify-between gap-3 px-3 py-1.5">
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
                {githubUrl && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-me-2 shrink-0 px-2"
                        nativeButton={false}
                        render={<LinkPrimitive to={githubUrl} target="_blank" />}
                        data-attr="today-report-code-github"
                    >
                        Open on GitHub
                        <IconExternal />
                    </Button>
                )}
            </figcaption>
            {excerpt ? (
                <pre className="TodayCodeExcerpt__body m-0 py-2 font-mono text-xs leading-relaxed">
                    {excerpt.lines.map((line, index) => (
                        <div key={index} className="flex">
                            <span
                                aria-hidden
                                className="w-12 shrink-0 select-none pe-3 text-right text-muted-foreground tabular-nums"
                            >
                                {excerpt.startLine + index}
                            </span>
                            <CodeLine
                                line={line}
                                marks={excerpt.marks.filter((mark) => mark.line === index)}
                                order={index}
                            />
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
