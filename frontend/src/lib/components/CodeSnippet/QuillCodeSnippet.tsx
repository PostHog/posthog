import { IconCollapse, IconCopy, IconExpand } from '@posthog/icons'
import { Button, Card, cn } from '@posthog/quill'

export function QuillCodeSnippet({
    children,
    className,
    actions,
    onCopy,
    expandable,
    expanded,
    expandLabel,
    onToggleExpanded,
}: {
    /** The highlighted code line. */
    children: React.ReactNode
    className?: string
    actions?: JSX.Element
    onCopy: (e: React.MouseEvent) => void
    expandable: boolean
    expanded: boolean
    expandLabel: string
    onToggleExpanded: () => void
}): JSX.Element {
    return (
        <div className={cn('flex min-w-0 flex-col gap-1', className)}>
            <Card flush className="flex-row items-start gap-0 py-0">
                <div className="min-w-0 flex-1 overflow-x-auto py-2.5 ps-3 font-mono text-xs">{children}</div>
                <div className="flex shrink-0 items-center gap-1 p-1.5">
                    {actions}
                    <Button
                        size="icon"
                        aria-label="Copy to clipboard"
                        tooltip="Copy to clipboard"
                        onClick={onCopy}
                        data-attr="copy-code-button"
                    >
                        <IconCopy />
                    </Button>
                </div>
            </Card>
            {expandable && (
                <Button variant="outline" className="w-full" onClick={onToggleExpanded}>
                    {expanded ? <IconCollapse /> : <IconExpand />}
                    {expandLabel}
                </Button>
            )}
        </div>
    )
}
