import { IconCopy, IconEllipsis, IconPencil, IconTrash, IconUndo } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

export interface QuillActionFilterGroupMenuProps {
    index: number
    onSplit: () => void
    onRename: () => void
    onDuplicate: () => void
    onDelete: () => void
}

export function QuillActionFilterGroupMenu({
    index,
    onSplit,
    onRename,
    onDuplicate,
    onDelete,
}: QuillActionFilterGroupMenuProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label="Show more actions"
                        tooltip="Show more actions"
                        data-attr={`group-filter-menu-${index}`}
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={onSplit} data-attr={`group-filter-split-${index}`}>
                    <IconUndo />
                    Split events
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={onRename} data-attr={`group-filter-rename-${index}`}>
                    <IconPencil />
                    Rename
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onDuplicate} data-attr={`group-filter-duplicate-${index}`}>
                    <IconCopy />
                    Duplicate
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onClick={onDelete} data-attr={`group-filter-delete-${index}`}>
                    <IconTrash />
                    Delete
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
