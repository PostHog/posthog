import { useActions } from 'kea'

import { IconArrowRight, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { dashboardsFileSystemLogic } from '../logics/dashboardsFileSystemLogic'

interface DashboardsTreeFolderMenuProps {
    // The folder this menu acts on; '' is the tree root ("All dashboards"), which only offers New folder.
    path: string
    // The folder's FileSystem row. Absent for folders inferred purely from a dashboard's path (no row, no
    // id) — those can't be moved/renamed/deleted, so only New subfolder is shown.
    entry?: FileSystemEntry
}

function openNameDialog(title: string, initialName: string, onSubmit: (name: string) => void): void {
    // Guard against a fast double-click submitting twice before the dialog closes — the create/rename
    // actions are fire-and-forget, so without this a double-click yields a duplicate folder / repeated rename.
    let submitted = false
    LemonDialog.openForm({
        title,
        initialValues: { folderName: initialName },
        content: (
            <LemonField name="folderName">
                <LemonInput placeholder="Enter a folder name" autoFocus />
            </LemonField>
        ),
        errors: { folderName: (name) => (!name?.trim() ? 'You must enter a folder name' : undefined) },
        onSubmit: ({ folderName }) => {
            if (submitted) {
                return
            }
            submitted = true
            onSubmit(folderName)
        },
    })
}

// Folder context menu for the tree arm — reuses the same move/rename/delete/create operations the sidebar
// tree uses (via dashboardsFileSystemLogic, which delegates to projectTreeDataLogic), but renders a scoped
// surface instead of the sidebar's full menu. Rendered through LemonTree's itemSideAction (hover ellipsis).
export function DashboardsTreeFolderMenu({ path, entry }: DashboardsTreeFolderMenuProps): JSX.Element {
    const { createFolder, renameFolder, deleteFolder } = useActions(dashboardsFileSystemLogic)
    const { openMoveToModal } = useActions(moveToLogic)
    const isRoot = path === ''
    const label = splitPath(path).at(-1) ?? path

    return (
        <>
            <DropdownMenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    openNameDialog(isRoot ? 'New folder' : 'New subfolder', '', (name) => createFolder(name, path))
                }}
                data-attr="dashboards-tree-new-folder"
            >
                <ButtonPrimitive menuItem>
                    <IconPlus className="size-4 text-tertiary" />
                    {isRoot ? 'New folder' : 'New subfolder'}
                </ButtonPrimitive>
            </DropdownMenuItem>
            {entry && (
                <>
                    <DropdownMenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            openNameDialog('Rename folder', label, (name) => renameFolder(entry, name))
                        }}
                        data-attr="dashboards-tree-rename-folder"
                    >
                        <ButtonPrimitive menuItem>
                            <IconPencil className="size-4 text-tertiary" />
                            Rename
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            openMoveToModal([entry])
                        }}
                        data-attr="dashboards-tree-move-folder"
                    >
                        <ButtonPrimitive menuItem>
                            <IconArrowRight className="size-4 text-tertiary" />
                            Move to...
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            deleteFolder(entry)
                        }}
                        data-attr="dashboards-tree-delete-folder"
                    >
                        <ButtonPrimitive menuItem>
                            <IconTrash className="size-4 text-danger" />
                            Delete
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </>
            )}
        </>
    )
}
