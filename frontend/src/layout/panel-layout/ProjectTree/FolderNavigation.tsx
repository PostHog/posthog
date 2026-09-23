import { IconChevronDown, IconFolder } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconArrowUp } from 'lib/lemon-ui/icons'

import { joinPath, parentPath, splitPath } from './utils'

export function FolderNavigation({
    folder,
    onOpen,
}: {
    folder: string
    onOpen: (folder: string) => void
}): JSX.Element {
    const parts = splitPath(folder)
    const ancestors = [
        { folder: '', label: 'Files' },
        ...parts.map((part, index) => ({ folder: joinPath(parts.slice(0, index + 1)), label: part })),
    ]
    return (
        <nav aria-label="Folder path" className="flex min-w-0 items-center gap-1 w-full">
            {folder && (
                <LemonButton
                    size="small"
                    icon={<IconArrowUp />}
                    aria-label="Parent folder"
                    tooltip="Go to parent folder"
                    data-attr="folder-navigation-up"
                    onClick={() => onOpen(parentPath(folder))}
                />
            )}
            <div className="min-w-0 flex-1">
                <LemonMenu
                    placement="bottom-start"
                    items={ancestors.map((ancestor) => ({
                        label: ancestor.label,
                        icon: <IconFolder />,
                        active: ancestor.folder === folder,
                        onClick: () => onOpen(ancestor.folder),
                    }))}
                >
                    <LemonButton
                        size="small"
                        fullWidth
                        className="min-w-0"
                        icon={<IconFolder />}
                        sideIcon={<IconChevronDown />}
                        tooltip={['Files', ...parts].join(' / ')}
                        aria-label="Choose folder level"
                        data-attr="folder-navigation-path"
                    >
                        <span className="truncate">{ancestors[ancestors.length - 1].label}</span>
                    </LemonButton>
                </LemonMenu>
            </div>
        </nav>
    )
}
