import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface ProjectTreeAction {
    type: 'move' | 'move-create' | 'create' | 'delete'
    item: FileSystemEntry
    path: string
    newPath?: string
}

export type FolderState = 'loading' | 'loaded' | 'has-more' | 'error'
