import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ShortTimestamp } from '../../trace/components/ShortTimestamp'

export interface ExampleItem {
    key: string
    title: string
    /** A second line, such as the error text or the model. */
    detail: string | null
    detailTone?: 'danger' | 'default'
    tags: { label: string; type: 'danger' | 'warning' | 'success' | 'muted' }[]
    timestamp: string
    /** A short value on the right, such as the latency. */
    metric: string | null
}

export interface ExampleListProps {
    title: string
    /** Null while loading. */
    examples: ExampleItem[] | null
    activeKey: string | null
    emptyText: string
    onOpen: (example: ExampleItem) => void
    'data-attr': string
}

export function ExampleList({
    title,
    examples,
    activeKey,
    emptyText,
    onOpen,
    'data-attr': dataAttr,
}: ExampleListProps): JSX.Element {
    return (
        <section className="flex flex-col gap-1.5">
            <h4 className="m-0 text-xs font-semibold text-secondary">{title}</h4>
            <div className="overflow-hidden rounded border border-primary">
                {examples === null ? (
                    <LemonSkeleton repeat={4} className="h-10 rounded-none" />
                ) : examples.length === 0 ? (
                    <div className="p-3 text-sm text-secondary">{emptyText}</div>
                ) : (
                    <ul className="m-0 list-none divide-y divide-primary p-0">
                        {examples.map((example) => (
                            <li key={example.key}>
                                <button
                                    type="button"
                                    onClick={() => onOpen(example)}
                                    aria-current={example.key === activeKey ? 'true' : undefined}
                                    // Inputs and error texts are raw event data, so keep them out of autocapture and replay.
                                    className={cn(
                                        'ph-no-capture flex w-full cursor-pointer items-start gap-3 px-3 py-2 text-left hover:bg-fill-highlight-50',
                                        example.key === activeKey && 'bg-fill-highlight-100'
                                    )}
                                    data-attr={dataAttr}
                                >
                                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                                        <span className="truncate text-sm font-semibold">{example.title}</span>
                                        {example.detail ? (
                                            <span
                                                className={cn(
                                                    'line-clamp-2 font-mono text-xs',
                                                    example.detailTone === 'danger' ? 'text-danger' : 'text-secondary'
                                                )}
                                            >
                                                {example.detail}
                                            </span>
                                        ) : null}
                                        <span className="flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                                            {example.tags.map((tag) => (
                                                <LemonTag key={tag.label} type={tag.type} size="small">
                                                    {tag.label}
                                                </LemonTag>
                                            ))}
                                            <ShortTimestamp time={example.timestamp} />
                                        </span>
                                    </span>
                                    {example.metric ? (
                                        <span className="shrink-0 text-sm tabular-nums">{example.metric}</span>
                                    ) : null}
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </section>
    )
}
