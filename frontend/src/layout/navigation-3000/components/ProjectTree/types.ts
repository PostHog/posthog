import { FeatureFlagKey } from 'lib/constants'

import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface ProjectTreeAction {
    type: 'move' | 'move-create' | 'create' | 'delete'
    item: FileSystemEntry
    path: string
    newPath?: string
}

export interface FileSystemImport extends FileSystemEntry {
    icon?: JSX.Element
    flag?: FeatureFlagKey
}
