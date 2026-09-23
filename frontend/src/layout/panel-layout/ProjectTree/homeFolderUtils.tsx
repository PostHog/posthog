import { IconInfo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { FileSystemHomeFolderApi } from '~/generated/core/api.schemas'

import { splitPath } from './utils'

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
                                    <span className="flex items-center gap-1 py-1 text-xs">
                                        <span>Empty home folder</span>
                                        <Tooltip
                                            title={
                                                <>
                                                    This folder is public, not private. Everyone in this project can see
                                                    what you put here. Find it at{' '}
                                                    <strong>{splitPath(homeFolder.path).join(' / ')}</strong>.
                                                </>
                                            }
                                            placement="right"
                                            openOnClick
                                        >
                                            <LemonButton
                                                size="xsmall"
                                                noPadding
                                                icon={<IconInfo />}
                                                aria-label="About your home folder"
                                                data-attr="home-folder-info"
                                                onClick={(event) => {
                                                    event.preventDefault()
                                                    event.stopPropagation()
                                                }}
                                            />
                                        </Tooltip>
                                    </span>
                                ),
                            }
                          : child
                  )
                : withHomeFolderEmptyState(item.children, homeFolder),
        }
    })
}
