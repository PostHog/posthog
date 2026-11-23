import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

export function QuillAPIKeyActionsMenu({
    keyLabel,
    onEdit,
    onRoll,
    onDelete,
}: {
    keyLabel: string
    onEdit: () => void
    onRoll: () => void
    onDelete: () => void
}): JSX.Element {
    const label = `Actions for key ${keyLabel}`

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button size="icon" aria-label={label} tooltip={label} />}>
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={onEdit}>Edit</DropdownMenuItem>
                <DropdownMenuItem onClick={onRoll}>Roll</DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={onDelete}>
                    Delete
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
