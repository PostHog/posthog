import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { FileSystemHomeFolderApi } from '~/generated/core/api.schemas'

export function isHomeFolder(item: TreeDataItem, homeFolder: FileSystemHomeFolderApi | null): boolean {
    return !!(
        homeFolder?.id &&
        item.record?.type === 'folder' &&
        (item.record.id === homeFolder.id ||
            (item.id.startsWith('shortcuts://') && item.record.ref === homeFolder.path))
    )
}

export function withHomeFolderEmptyState(
    items: TreeDataItem[],
    homeFolder: FileSystemHomeFolderApi | null
): TreeDataItem[] {
    if (!homeFolder?.id) {
        return items
    }
    return items.map((item) => {
        if (!item.children) {
            return item
        }
        return {
            ...item,
            children: isHomeFolder(item, homeFolder)
                ? item.children.map((child) =>
                      child.type === 'empty-folder'
                          ? {
                                ...child,
                                displayName: (
                                    <span className="block py-1 text-xs leading-relaxed">
                                        <span className="block">This is your public home folder in this project.</span>
                                        <span className="block mt-1">
                                            Drag files here, or use the folder's menu to create something new.
                                        </span>
                                    </span>
                                ),
                            }
                          : child
                  )
                : withHomeFolderEmptyState(item.children, homeFolder),
        }
    })
}
