import { baseObjectType, libraryObjectHref } from 'scenes/library/libraryUtils'

import { FileSystemEntry } from '~/queries/schema/schema-general'

/** Recently viewed objects for the home, without tasks, which are agent sessions rather than things people look at. */
export function recentObjectsForHome(recents: FileSystemEntry[], limit: number): FileSystemEntry[] {
    return recents
        .filter((entry) => libraryObjectHref(entry) !== null && baseObjectType(entry.type) !== 'task')
        .slice(0, limit)
}
