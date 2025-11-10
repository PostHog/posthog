import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { ReactNode, useRef, useState } from 'react'

import { IconFolder, IconFolderOpen } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { ProjectTreeLogicProps, projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { ScrollableShadows } from '~/lib/components/ScrollableShadows/ScrollableShadows'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { itemSelectModalLogic } from './itemSelectModalLogic'

export interface ItemSelectModalProps {
    /** Class name for the component */
    className?: string
    /** Include "products://" in the final path */
    includeProtocol?: boolean
    /** Include root item in the tree as a selectable item */
    includeRoot?: boolean
}

export interface ItemSelectModalButtonProps {
    /** Trigger the modal */
    buttonProps?: ButtonPrimitiveProps
}

/** Input component for selecting a item */
let counter = 0

function RootFolderButton({
    children,
    onClick,
    active,
}: {
    children: ReactNode
    onClick: () => void
    active: boolean
}): JSX.Element {
    return (
        <ButtonPrimitive
            className={cn('flex gap-2 px-2 py-1 border border-primary rounded hover:border-secondary', {
                'border-accent': active,
            })}
            onClick={onClick}
        >
            {active ? <IconFolderOpen className="text-accent" /> : <IconFolder />}
            {children}
        </ButtonPrimitive>
    )
}

export function ItemSelectModalButton({ buttonProps }: ItemSelectModalButtonProps): JSX.Element {
    const { openItemSelectModal } = useActions(itemSelectModalLogic)

    return (
        <>
            <ButtonPrimitive onClick={() => openItemSelectModal()} {...buttonProps}>
                {buttonProps?.children || 'Select an item'}
            </ButtonPrimitive>
        </>
    )
}

export function ItemSelectModal({ className, includeProtocol, includeRoot }: ItemSelectModalProps): JSX.Element {
    const [treeRoot, setTreeRoot] = useState('project://')
    const [key] = useState(() => `item-select-${counter++}`)
    const props: ProjectTreeLogicProps = { key, root: treeRoot, includeRoot, hideFolders: ['shortcuts://'] }
    const inputRef = useRef<HTMLInputElement>(null)
    const [selectedItem, setSelectedItem] = useState<TreeDataItem | null>(null)
    const { isOpen } = useValues(itemSelectModalLogic)
    const { closeItemSelectModal, submitForm, setFormValue } = useActions(itemSelectModalLogic)
    const { searchTerm, expandedSearchFolders, expandedFolders, fullFileSystemFiltered, treeTableKeys, editingItemId } =
        useValues(projectTreeLogic(props))
    const { setSearchTerm, setExpandedSearchFolders, setExpandedFolders, setEditingItemId, rename, toggleFolderOpen } =
        useActions(projectTreeLogic(props))

    const treeRef = useRef<LemonTreeRef>(null)

    useOnMountEffect(() => {
        const timeout = setTimeout(() => {
            if (inputRef.current) {
                inputRef.current?.focus()
            }
        }, 50)

        return () => clearTimeout(timeout)
    })

    function handleSelectItem(item: TreeDataItem): void {
        setSelectedItem(item)
        setFormValue('item', item)
    }

    return (
        <>
            <LemonModal
                onClose={() => {
                    closeItemSelectModal()
                    setSelectedItem(null)
                    setSearchTerm('')
                    setTreeRoot('project://')
                }}
                isOpen={isOpen}
                title="Choose an item"
                // This is a bit of a hack. Without it, the flow "insight" -> "add to dashboard button" ->
                // "new dashboard template picker modal" -> "save dashboard to modal" wouldn't work.
                // Since MoveToModal is added to the DOM earlier as part of global modals, it's below it in hierarchy.
                zIndex="1169"
                // Make modal hug the top of the page as the modal changes size
                overlayClassName="items-start"
                footer={
                    <>
                        <div className="flex-1" />
                        <LemonButton
                            type="primary"
                            onClick={submitForm}
                            data-attr="item-select-modal-add-button"
                            disabledReason={
                                !selectedItem
                                    ? 'Please select an item'
                                    : selectedItem.record?.type === 'folder' &&
                                        selectedItem.record?.protocol === 'new://'
                                      ? 'Please select an item inside the folder'
                                      : undefined
                            }
                        >
                            Add {selectedItem?.name || selectedItem?.displayName}
                        </LemonButton>
                    </>
                }
            >
                <div className="w-192 max-w-full">
                    <Form logic={itemSelectModalLogic} formKey="form">
                        <LemonField name="item">
                            <div className="flex flex-col gap-2">
                                <div className="flex gap-2 overflow-auto">
                                    <RootFolderButton
                                        onClick={() => setTreeRoot('project://')}
                                        active={treeRoot === 'project://'}
                                    >
                                        Project
                                    </RootFolderButton>
                                    <RootFolderButton
                                        onClick={() => setTreeRoot('products://')}
                                        active={treeRoot === 'products://'}
                                    >
                                        Products
                                    </RootFolderButton>
                                    <RootFolderButton
                                        onClick={() => setTreeRoot('data://')}
                                        active={treeRoot === 'data://'}
                                    >
                                        Data
                                    </RootFolderButton>
                                    <RootFolderButton
                                        onClick={() => setTreeRoot('persons://')}
                                        active={treeRoot === 'persons://'}
                                    >
                                        Persons
                                    </RootFolderButton>
                                    <RootFolderButton
                                        onClick={() => setTreeRoot('new://')}
                                        active={treeRoot === 'new://'}
                                    >
                                        New
                                    </RootFolderButton>
                                </div>

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

                                <ScrollableShadows
                                    direction="vertical"
                                    className={cn(
                                        'bg-surface-primary border rounded group/colorful-product-icons colorful-product-icons-true',
                                        className
                                    )}
                                >
                                    <LemonTree
                                        ref={treeRef}
                                        selectMode="all"
                                        className="px-0 py-1"
                                        data={fullFileSystemFiltered}
                                        mode="tree"
                                        tableViewKeys={treeTableKeys}
                                        defaultSelectedFolderOrNodeId=""
                                        isItemActive={() => false}
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
                                        onSetExpandedItemIds={
                                            searchTerm ? setExpandedSearchFolders : setExpandedFolders
                                        }
                                        enableDragAndDrop={false}
                                        renderItem={(item) => {
                                            const isNew =
                                                item.record?.created_at &&
                                                dayjs().diff(dayjs(item.record?.created_at), 'minutes') < 3
                                            return (
                                                <span className="truncate">
                                                    <span
                                                        className={cn('truncate', {
                                                            'font-semibold':
                                                                item.record?.type === 'folder' &&
                                                                item.type !== 'empty-folder',
                                                        })}
                                                    >
                                                        {item.displayName}{' '}
                                                        {isNew ? (
                                                            <LemonTag
                                                                type="highlight"
                                                                size="small"
                                                                className="ml-1 relative top-[-1px]"
                                                            >
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
