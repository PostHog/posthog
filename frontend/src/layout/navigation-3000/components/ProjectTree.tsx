import { DndContext, useDraggable, useDroppable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { IconUpload } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ReactNode, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { FileSystemEntry } from '~/queries/schema'

import { navigation3000Logic } from '../navigationLogic'
import { NavbarBottom } from './NavbarBottom'
import { projectTreeLogic } from './projectTreeLogic'

// TODO: Swap out for a better DnD approach
// Currently you can only drag the title text, and must click on the icon or to the right of it to trigger a click
function Draggable(props: { id: string; children: ReactNode }): JSX.Element {
    const { attributes, listeners, setNodeRef, transform } = useDraggable({
        id: props.id,
    })
    const style = {
        transform: CSS.Translate.toString(transform),
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div ref={setNodeRef} style={style} {...listeners} {...attributes}>
            {props.children}
        </div>
    )
}
export function Droppable(props: { id: string; children: ReactNode }): JSX.Element {
    const { setNodeRef } = useDroppable({ id: props.id })

    return <div ref={setNodeRef}>{props.children}</div>
}

export function TreeView(): JSX.Element {
    const { theme } = useValues(themeLogic)
    const { isNavShown, mobileLayout } = useValues(navigation3000Logic)
    const { toggleNavCollapsed, hideNavOnMobile } = useActions(navigation3000Logic)
    const { treeData, viableItems, loadingPaths, unappliedPaths } = useValues(projectTreeLogic)
    const { addFolder, deleteItem, moveItem } = useActions(projectTreeLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)

    return (
        <>
            <nav className={clsx('Navbar3000', !isNavShown && 'Navbar3000--hidden')} ref={containerRef}>
                <div
                    className="Navbar3000__content w-80"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={theme?.sidebarStyle}
                >
                    <DndContext
                        onDragEnd={({ active, over }) => {
                            const oldPath = active.id as string
                            const folder = over?.id
                            if (folder === oldPath) {
                                // We can't click on draggable items. If we drag to itself, assume it's a click
                                // TODO: clicking on expandable folders does not work as we can't control
                                // the open/closed state of the tree - only files work.
                                const item = viableItems.find((i) => i.path === oldPath)
                                if (item && item.href) {
                                    router.actions.push(item.href)
                                }
                            } else if (folder === '') {
                                const oldSplit = oldPath.split('/')
                                const oldFile = oldSplit.pop()
                                if (oldFile && oldSplit.length > 0) {
                                    moveItem(oldPath, oldFile)
                                }
                            } else if (folder) {
                                const item = viableItems.find((i) => i.path === folder)
                                if (!item || item.type === 'folder') {
                                    const oldSplit = oldPath.split('/')
                                    const oldFile = oldSplit.pop()
                                    const newFile = folder + '/' + oldFile
                                    if (newFile !== oldPath) {
                                        moveItem(oldPath, newFile)
                                    }
                                }
                            }
                        }}
                    >
                        <ScrollableShadows innerClassName="Navbar3000__top" direction="vertical">
                            <LemonTree
                                className="px-0 py-1"
                                data={treeData}
                                renderItem={(item, children): JSX.Element => {
                                    const path = item.record?.path || ''
                                    const loading =
                                        typeof item.record?.path === 'string' || item.record?.type === 'project' ? (
                                            loadingPaths[path] ? (
                                                <Spinner className="ml-1" />
                                            ) : unappliedPaths[path] ? (
                                                <IconUpload className="ml-1 text-warning" />
                                            ) : undefined
                                        ) : undefined
                                    if (item.record?.type === 'project') {
                                        return (
                                            <Droppable id="">
                                                {children}
                                                {loading}
                                            </Droppable>
                                        )
                                    } else if (path) {
                                        return (
                                            <Droppable id={path}>
                                                <Draggable id={path}>
                                                    {children}
                                                    {loading}
                                                </Draggable>
                                            </Droppable>
                                        )
                                    }
                                    return (
                                        <>
                                            {children}
                                            {loading}
                                        </>
                                    )
                                }}
                                right={({ record }) =>
                                    record?.created_at || record?.type ? (
                                        <More
                                            size="xsmall"
                                            onClick={(e) => e.stopPropagation()}
                                            overlay={
                                                <>
                                                    {record?.type === 'folder' || record?.type === 'project' ? (
                                                        <LemonButton
                                                            onClick={() => {
                                                                const folder = prompt(
                                                                    record.path
                                                                        ? `Create a folder under "${record.path}":`
                                                                        : 'Create a new folder:',
                                                                    ''
                                                                )
                                                                if (folder) {
                                                                    addFolder(
                                                                        record.path
                                                                            ? record.path + '/' + folder
                                                                            : folder
                                                                    )
                                                                }
                                                            }}
                                                            fullWidth
                                                        >
                                                            New Folder
                                                        </LemonButton>
                                                    ) : null}
                                                    {record.path ? (
                                                        <LemonButton
                                                            onClick={() => {
                                                                const oldPath = record.path
                                                                const folder = prompt('New name?', oldPath)
                                                                if (folder) {
                                                                    moveItem(oldPath, folder)
                                                                }
                                                            }}
                                                            fullWidth
                                                        >
                                                            Rename
                                                        </LemonButton>
                                                    ) : null}
                                                    {record.path ? (
                                                        <LemonButton
                                                            onClick={() => {
                                                                void navigator.clipboard.writeText(record.path)
                                                            }}
                                                            fullWidth
                                                        >
                                                            Copy Path
                                                        </LemonButton>
                                                    ) : null}
                                                    {record?.created_at ? (
                                                        <LemonButton
                                                            onClick={() => deleteItem(record as FileSystemEntry)}
                                                            fullWidth
                                                        >
                                                            Delete
                                                        </LemonButton>
                                                    ) : null}
                                                </>
                                            }
                                        />
                                    ) : undefined
                                }
                            />
                        </ScrollableShadows>
                    </DndContext>
                    <NavbarBottom />
                </div>
                {!mobileLayout && (
                    <Resizer
                        logicKey="navbar"
                        placement="right"
                        containerRef={containerRef}
                        closeThreshold={100}
                        onToggleClosed={(shouldBeClosed) => toggleNavCollapsed(shouldBeClosed)}
                        onDoubleClick={() => toggleNavCollapsed()}
                    />
                )}
            </nav>
            {mobileLayout && (
                <div
                    className={clsx('Navbar3000__overlay', !isNavShown && 'Navbar3000--hidden')}
                    onClick={() => hideNavOnMobile()}
                />
            )}
        </>
    )
}
