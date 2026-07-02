import clsx from 'clsx'

/**
 * Renders a unified diff with add/remove/hunk coloring. Mirrors desktop `DiffBlock`: each line is
 * classed by its leading character (`+`/`-`/`@@`), with `+++`/`---` file headers treated as context.
 */
export function DiffBlock({ diff }: { diff: string }): JSX.Element {
    const lines = diff.replace(/\n$/, '').split('\n')
    return (
        <pre className="max-h-96 overflow-auto rounded border border-primary bg-surface-primary p-2 text-[11px] leading-[1.45] font-mono m-0">
            {lines.map((line, i) => {
                const added = line.startsWith('+') && !line.startsWith('+++')
                const removed = line.startsWith('-') && !line.startsWith('---')
                const hunk = line.startsWith('@@')
                return (
                    <span
                        key={i}
                        className={clsx(
                            'block whitespace-pre',
                            added && 'bg-success-highlight text-success',
                            removed && 'bg-danger-highlight text-danger',
                            hunk && 'text-tertiary',
                            !added && !removed && !hunk && 'text-default'
                        )}
                    >
                        {line === '' ? ' ' : line}
                    </span>
                )
            })}
        </pre>
    )
}
