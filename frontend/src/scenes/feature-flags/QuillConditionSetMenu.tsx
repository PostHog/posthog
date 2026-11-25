import { IconCopy, IconEllipsis, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

export function QuillConditionSetMenu({
    canRemove,
    onDuplicate,
    onRemove,
}: {
    canRemove: boolean
    onDuplicate: () => void
    onRemove: () => void
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button size="icon-sm" aria-label="Condition set actions" tooltip="Condition set actions" />}
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={onDuplicate}>
                    <IconCopy />
                    Duplicate condition set
                </DropdownMenuItem>
                {canRemove && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={onRemove}>
                            <IconTrash />
                            Remove condition set
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
