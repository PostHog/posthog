import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function QuillAddGoalLineButton({
    onClick,
    className,
}: {
    onClick: () => void
    className: string
}): JSX.Element {
    return (
        <Button variant="outline" onClick={onClick} className={className}>
            <IconPlus />
            Add goal line
        </Button>
    )
}
