import { IconCopy } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function QuillCopyableCode({
    value,
    label,
    onCopy,
}: {
    value: string
    label: string
    onCopy: () => void
}): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-1">
            <code data-quill className="max-w-50 truncate rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs">
                {value}
            </code>
            <Button size="icon-xs" aria-label={label} tooltip={label} onClick={onCopy}>
                <IconCopy />
            </Button>
        </div>
    )
}
