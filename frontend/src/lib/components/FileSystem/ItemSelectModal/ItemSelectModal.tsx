import { useActions, useValues } from 'kea'
import { SelectedFolder } from 'lib/components/FileSystem/SaveTo/saveToLogic'
import { dayjs } from 'lib/dayjs'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { useEffect, useRef, useState } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { projectTreeLogic, ProjectTreeLogicProps } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { ScrollableShadows } from '~/lib/components/ScrollableShadows/ScrollableShadows'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { itemSelectModalLogic } from './itemSelectModalLogic'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface ItemSelectModalProps {
    /** The folder to select */
    value?: string
    /** Callback when a folder is selected */
    onChange?: (selectedFolder: SelectedFolder) => void
    /** Class name for the component */
    className?: string
    /** Root for folder */
    root?: string
    /** Include "products://" in the final path */
    includeProtocol?: boolean
    /** Include root item in the tree as a selectable item */
    includeRoot?: boolean
    /** Trigger the modal */
    buttonProps?: ButtonPrimitiveProps
}

/** Input component for selecting a folder */
let counter = 0

export function ItemSelectModal({
    root,
    className,
    includeProtocol,
    includeRoot,
    buttonProps,
}: ItemSelectModalProps): JSX.Element {
    const [value, setValue] = useState<string | undefined>(undefined)
    const [key] = useState(() => `item-select-${counter++}`)
    const props: ProjectTreeLogicProps = { key, root, includeRoot, hideFolders: ['shortcuts://'] }
    const inputRef = useRef<HTMLInputElement>(null)
    const [selectedItem, setSelectedItem] = useState<TreeDataItem | null>(null)
    const { isOpen, form } = useValues(itemSelectModalLogic)
    const { openItemSelectModal, closeItemSelectModal, submitForm, setFormValue } = useActions(itemSelectModalLogic)
    const { searchTerm, expandedSearchFolders, expandedFolders, fullFileSystemFiltered, treeTableKeys, editingItemId } =
        useValues(projectTreeLogic(props))
    const {
        setSearchTerm,
        setExpandedSearchFolders,
        setExpandedFolders,
        expandProjectFolder,
        setEditingItemId,
        rename,
        toggleFolderOpen,
    } = useActions(projectTreeLogic(props))

    const treeRef = useRef<LemonTreeRef>(null)

    useEffect(() => {
        if (includeProtocol) {
            if (value?.startsWith('project://')) {
                expandProjectFolder(value.replace('project://', ''))
            }
        } else {
            expandProjectFolder(value || '')
        }
    }, [value])

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (inputRef.current) {
                inputRef.current?.focus()
            }
        }, 50)
        return () => {
            clearTimeout(timeout)
        }
    }, [])

    function handleSelectItem(item: TreeDataItem): void {
        setSelectedItem(item)
        console.log('item', item)
        setFormValue('item', item)
    }

    console.log('form', form)
    return (
        <>
            <ButtonPrimitive onClick={() => openItemSelectModal()} {...buttonProps}>
                {buttonProps ? buttonProps.children : 'Select an item'}
            </ButtonPrimitive>

            <LemonModal
                onClose={closeItemSelectModal}
                isOpen={isOpen}
                title="Choose an item"
                description={
                    <>
                        Select an item
                    </>
                }
                // This is a bit of a hack. Without it, the flow "insight" -> "add to dashboard button" ->
                // "new dashboard template picker modal" -> "save dashboard to modal" wouldn't work.
                // Since MoveToModal is added to the DOM earlier as part of global modals, it's below it in hierarchy.
                zIndex="1169"
                footer={
                    <>
                        <div className="flex-1" />
                        <LemonButton
                            type="primary"
                            onClick={submitForm}
                            data-attr="move-to-modal-move-button"
                            disabledReason={!selectedItem ? 'Please select an item' : undefined}
                        >
                            Add {selectedItem?.displayName || selectedItem?.name}
                        </LemonButton>
                    </>
                }
            >
                <div className="w-192 max-w-full">
                    <Form logic={itemSelectModalLogic} formKey="form">
                        <LemonField name="item">
                            <div className="flex flex-col gap-2">
                                <LemonInput
                                    type="search"
                                    placeholder="Search"
                                    fullWidth
                                    size="small"
                                    onChange={(search) => setSearchTerm(search)}
                                    value={searchTerm}
                                    data-attr="folder-select-search-input"
                                    autoFocus
                                    inputRef={inputRef}
                                    onKeyDown={(e) => {
                                        if (e.key === 'ArrowDown') {
                                            e.preventDefault() // Prevent scrolling
                                            const visibleItems = treeRef?.current?.getVisibleItems()
                                            if (visibleItems && visibleItems.length > 0) {
                                                e.currentTarget.blur() // Remove focus from input
                                                treeRef?.current?.focusItem(visibleItems[0].id)
                                            }
                                        }
                                    }}
                                />
                                <ScrollableShadows direction="vertical" className={cn('bg-surface-primary border rounded', className)}>
                                    <LemonTree
                                        ref={treeRef}
                                        selectMode="all"
                                        className="px-0 py-1"
                                        data={fullFileSystemFiltered}
                                        mode="tree"
                                        tableViewKeys={treeTableKeys}
                                        defaultSelectedFolderOrNodeId={''}
                                        isItemActive={(item) => item.record?.path === value}
                                        isItemEditing={(item) => {
                                            return editingItemId === item.id
                                        }}
                                        onItemNameChange={(item, name) => {
                                            if (item.name !== name) {
                                                rename(name, item.record as unknown as FileSystemEntry)
                                            }
                                            // Clear the editing item id when the name changes
                                            setEditingItemId('')
                                        }}
                                        showFolderActiveState={true}
                                        checkedItemCount={0}
                                        onFolderClick={(folder, isExpanded) => {
                                            if (folder) {
                                                // const folderPath = includeProtocol ? folder.id : folder.record?.path ?? ''

                                                if (includeProtocol) {
                                                    toggleFolderOpen(folder.id, isExpanded)
                                                } else {
                                                    toggleFolderOpen(folder.id || '', isExpanded)
                                                }
                                                handleSelectItem(folder)
                                            }
                                        }}
                                        onItemClick={(item, event) => {
                                            event.preventDefault()
                                            item && handleSelectItem(item)
                                        }}
                                        expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                                        onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
                                        enableDragAndDrop={false}
                                        renderItem={(item) => {
                                            const isNew =
                                                item.record?.created_at && dayjs().diff(dayjs(item.record?.created_at), 'minutes') < 3
                                            return (
                                                <span className="truncate">
                                                    <span
                                                        className={cn('truncate', {
                                                            'font-semibold': item.record?.type === 'folder' && item.type !== 'empty-folder',
                                                        })}
                                                    >
                                                        {item.displayName}{' '}
                                                        {isNew ? (
                                                            <LemonTag type="highlight" size="small" className="ml-1 relative top-[-1px]">
                                                                New
                                                            </LemonTag>
                                                        ) : null}
                                                    </span>
                                                </span>
                                            )
                                        }}
                                    />
                                </ScrollableShadows>
                            </div>
                        </LemonField>
                    </Form>
                </div>
            </LemonModal>
        </>
    )
}
