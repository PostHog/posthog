import { useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonTree, type TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { ScrollableShadows } from '~/lib/components/ScrollableShadows/ScrollableShadows'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { SavedTicketView } from '../../types'
import { FiltersSummary } from './FiltersSummary'
import { SaveViewModal } from './SaveViewModal'
import { folderPathFromNodeId } from './ticketViewFolders'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

/** Keeps a menu click from also selecting the tree row underneath it. */
const stop =
    (run: () => void) =>
    (event: { stopPropagation: () => void }): void => {
        event.stopPropagation()
        run()
    }

function openFolderPicker({
    title,
    initialFolder,
    folderPaths,
    onSubmit,
}: {
    title: string
    initialFolder: string
    folderPaths: string[]
    onSubmit: (folder: string) => void
}): void {
    LemonDialog.openForm({
        title,
        initialValues: { folder: initialFolder },
        content: (
            <LemonField
                name="folder"
                help='Use "/" to nest, for example Escalations/EU. Leave it empty to move to the top level.'
            >
                {({ value, onChange }) => (
                    <LemonInputSelect
                        mode="single"
                        allowCustomValues
                        placeholder="Choose or type a folder"
                        value={value ? [value] : []}
                        onChange={(folders) => onChange(folders[0] ?? '')}
                        options={folderPaths.map((path) => ({ key: path, label: path }))}
                    />
                )}
            </LemonField>
        ),
        onSubmit: ({ folder }) => onSubmit(folder ?? ''),
    })
}

export function SavedViewsModal({ id }: TicketViewsLogicProps): JSX.Element {
    const {
        isModalOpen,
        viewTree,
        viewsLoading,
        currentFilters,
        searchTerm,
        effectiveExpandedFolderIds,
        folderPaths,
        favoritingShortIds,
        movingFolders,
    } = useValues(ticketViewsLogic({ id }))
    const {
        closeModal,
        openSaveModal,
        deleteView,
        loadView,
        updateView,
        toggleFavorite,
        setSearchTerm,
        setExpandedFolderIds,
        toggleFolderExpanded,
        moveViewToFolder,
        moveFolder,
        renameFolder,
    } = useActions(ticketViewsLogic({ id }))
    const [editingItemId, setEditingItemId] = useState('')
    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined

    const disabledReasons = { [editDisabledReason ?? '']: !!editDisabledReason }

    /**
     * One builder feeds both surfaces: right-click for people who know it's there, and the hover
     * ellipsis for everyone else. Radix menu items take `disabled`, so the reason rides on the
     * ButtonPrimitive inside.
     */
    function renderRowMenu(
        item: TreeDataItem,
        MenuGroup: typeof ContextMenuGroup | typeof DropdownMenuGroup,
        MenuItem: typeof ContextMenuItem | typeof DropdownMenuItem
    ): ReactNode {
        if (item.record?.type === 'view') {
            const view: SavedTicketView = item.record.view
            return (
                <MenuGroup>
                    <MenuItem asChild onClick={stop(() => loadView(view))}>
                        <ButtonPrimitive menuItem data-attr="saved-view-load">
                            Load
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuItem asChild onClick={stop(() => toggleFavorite(view))}>
                        <ButtonPrimitive menuItem disabledReasons={disabledReasons}>
                            {view.is_favorited ? 'Remove from favorites' : 'Add to favorites'}
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuItem
                        asChild
                        onClick={stop(() =>
                            LemonDialog.openForm({
                                title: 'Rename view',
                                initialValues: { name: view.name },
                                content: (
                                    <LemonField name="name">
                                        <LemonInput autoFocus placeholder="View name" />
                                    </LemonField>
                                ),
                                errors: { name: (name) => (!name?.trim() ? 'Enter a name' : undefined) },
                                onSubmit: ({ name }) => updateView(view.short_id, { name: name.trim() }),
                            })
                        )}
                    >
                        <ButtonPrimitive menuItem disabledReasons={disabledReasons}>
                            Rename
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuItem
                        asChild
                        onClick={stop(() =>
                            openFolderPicker({
                                title: `Move "${view.name}"`,
                                initialFolder: view.folder,
                                folderPaths,
                                onSubmit: (folder) => moveViewToFolder(view.short_id, folder),
                            })
                        )}
                    >
                        <ButtonPrimitive menuItem disabledReasons={disabledReasons}>
                            Move to folder
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuItem
                        asChild
                        onClick={stop(() =>
                            LemonDialog.open({
                                title: `Update "${view.name}"?`,
                                description: (
                                    <div className="space-y-2">
                                        <div>
                                            Replace the saved filters on this view with the filters currently applied to
                                            the ticket list. The view keeps its name and link.
                                        </div>
                                        <FiltersSummary filters={currentFilters} />
                                    </div>
                                ),
                                primaryButton: {
                                    children: 'Update view',
                                    type: 'primary',
                                    onClick: () => updateView(view.short_id, { filters: { ...currentFilters } }),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        )}
                    >
                        <ButtonPrimitive menuItem disabledReasons={disabledReasons}>
                            Update with current filters
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuItem
                        asChild
                        onClick={stop(() =>
                            LemonDialog.open({
                                title: `Delete "${view.name}"?`,
                                description: 'This view will be permanently deleted. This action cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    status: 'danger',
                                    onClick: () => deleteView(view.short_id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        )}
                    >
                        <ButtonPrimitive menuItem variant="danger" disabledReasons={disabledReasons}>
                            Delete
                        </ButtonPrimitive>
                    </MenuItem>
                </MenuGroup>
            )
        }

        const path = folderPathFromNodeId(item.id)
        if (!path) {
            // The Favorites node is not a real folder, so it has nothing to move or rename
            return undefined
        }
        return (
            <MenuGroup>
                <MenuItem asChild onClick={stop(() => setEditingItemId(item.id))}>
                    <ButtonPrimitive menuItem disabledReasons={disabledReasons}>
                        Rename folder
                    </ButtonPrimitive>
                </MenuItem>
                <MenuItem
                    asChild
                    onClick={stop(() =>
                        openFolderPicker({
                            title: `Move "${item.name}"`,
                            initialFolder: path,
                            folderPaths: folderPaths.filter((candidate) => candidate !== path),
                            onSubmit: (folder) => moveFolder(path, folder),
                        })
                    )}
                >
                    <ButtonPrimitive menuItem disabledReasons={disabledReasons}>
                        Move folder
                    </ButtonPrimitive>
                </MenuItem>
            </MenuGroup>
        )
    }

    return (
        <>
            <LemonModal
                isOpen={isModalOpen}
                onClose={closeModal}
                title="Saved views"
                width={720}
                footer={
                    <div className="flex justify-between w-full">
                        <LemonButton type="primary" onClick={openSaveModal} disabledReason={editDisabledReason}>
                            Save current view
                        </LemonButton>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search views and folders"
                        value={searchTerm}
                        onChange={setSearchTerm}
                        autoFocus
                    />
                    {viewsLoading && !viewTree.length ? (
                        <div className="flex justify-center py-8">
                            <Spinner />
                        </div>
                    ) : !viewTree.length ? (
                        <div className="text-muted text-center py-8">
                            {searchTerm ? 'No views match your search.' : 'No saved views yet.'}
                        </div>
                    ) : (
                        <ScrollableShadows direction="vertical" className="border rounded max-h-100">
                            <LemonTree
                                data={viewTree}
                                className="px-0 py-1"
                                expandedItemIds={effectiveExpandedFolderIds}
                                onSetExpandedItemIds={setExpandedFolderIds}
                                onFolderClick={(folder) => folder && toggleFolderExpanded(folder.id)}
                                onItemClick={(item) => item?.record?.type === 'view' && loadView(item.record.view)}
                                isItemLoading={(item) => {
                                    if (item.record?.type === 'view') {
                                        return favoritingShortIds.includes(item.record.view.short_id)
                                    }
                                    const path = folderPathFromNodeId(item.id)
                                    return !!path && movingFolders.includes(path)
                                }}
                                isItemEditing={(item) => editingItemId === item.id}
                                onItemNameChange={(item, name) => {
                                    const path = folderPathFromNodeId(item.id)
                                    if (path && item.name !== name) {
                                        renameFolder(path, name)
                                    }
                                    setEditingItemId('')
                                }}
                                itemContextMenu={(item) => renderRowMenu(item, ContextMenuGroup, ContextMenuItem)}
                                itemSideAction={(item) => renderRowMenu(item, DropdownMenuGroup, DropdownMenuItem)}
                                enableDragAndDrop={false}
                            />
                        </ScrollableShadows>
                    )}
                </div>
            </LemonModal>
            <SaveViewModal id={id} />
        </>
    )
}
