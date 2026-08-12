import {
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface ProjectTreeAction {
    type: 'prepare-move' | 'move' | 'link' | 'prepare-link' | 'create' | 'prepare-delete' | 'delete'
    item: FileSystemEntry
    path: string
    newPath?: string
    /**
     * Set on move actions to tie them to the `moveItems` batch that issued them, so the batch reports and
     * undoes as one. It rides on the action because a folder move settles in a second, re-queued action
     * (`prepare-move` becomes `move`) that must still resolve to the batch that started it.
     */
    batchId?: string
}

export type FolderState = 'loading' | 'loaded' | 'has-more' | 'error'

export interface CustomMenuProps {
    MenuItem?: typeof ContextMenuItem | typeof DropdownMenuItem
    MenuGroup?: typeof ContextMenuGroup | typeof DropdownMenuGroup
    MenuSeparator?: typeof ContextMenuSeparator | typeof DropdownMenuSeparator
    MenuSub?: typeof ContextMenuSub | typeof DropdownMenuSub
    MenuSubTrigger?: typeof ContextMenuSubTrigger | typeof DropdownMenuSubTrigger
    MenuSubContent?: typeof ContextMenuSubContent | typeof DropdownMenuSubContent
    onLinkClick?: (keyboardAction?: boolean) => void
}
