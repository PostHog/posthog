import { ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'

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
}
