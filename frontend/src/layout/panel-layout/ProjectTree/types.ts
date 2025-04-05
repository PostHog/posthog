import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface ProjectTreeAction {
    type: 'prepare-move' | 'move' | 'link' | 'prepare-link' | 'create' | 'prepare-delete' | 'delete'
    item: FileSystemEntry
    path: string
    newPath?: string
}

export type FolderState = 'loading' | 'loaded' | 'has-more' | 'error'
