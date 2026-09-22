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
     * Ties a move to the `moveItems` batch that issued it. It rides on the action because a folder move
     * settles in a second, re-queued action (`prepare-move` becomes `move`) that must still find its batch.
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
