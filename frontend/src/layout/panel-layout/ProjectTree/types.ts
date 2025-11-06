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
}

export type FolderState = 'loading' | 'loaded' | 'has-more' | 'error'

export interface CustomMenuProps {
    MenuItem?: typeof ContextMenuItem | typeof DropdownMenuItem
    MenuSeparator?: typeof ContextMenuSeparator | typeof DropdownMenuSeparator
    MenuSub?: typeof ContextMenuSub | typeof DropdownMenuSub
    MenuSubTrigger?: typeof ContextMenuSubTrigger | typeof DropdownMenuSubTrigger
    MenuSubContent?: typeof ContextMenuSubContent | typeof DropdownMenuSubContent
    MenuGroup?: typeof ContextMenuGroup | typeof DropdownMenuGroup
    onLinkClick?: (keyboardAction?: boolean) => void
}
