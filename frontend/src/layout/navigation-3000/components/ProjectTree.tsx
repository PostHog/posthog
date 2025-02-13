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

import { navigation3000Logic } from '../navigationLogic'
import { NavbarBottom } from './NavbarBottom'
import { projectTreeLogic } from './projectTreeLogic'

// TODO: Swap out for something that works better
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
                                // TODO: clicking on expandable folders does not work - only files work.
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
                                const oldSplit = oldPath.split('/')
                                const oldFile = oldSplit.pop()
                                const newFile = folder + '/' + oldFile
                                if (newFile !== oldPath) {
                                    moveItem(oldPath, newFile)
                                }
                            }
                        }}
                    >
                        <ScrollableShadows innerClassName="Navbar3000__top" direction="vertical">
                            <LemonTree
                                className="px-0 py-1"
                                data={treeData}
                                renderItem={(item, children): JSX.Element => {
                                    const path = item.data?.path || ''
                                    const loading =
                                        typeof item.data?.path === 'string' || item.data?.type === 'project' ? (
                                            loadingPaths[path] ? (
                                                <Spinner className="ml-1" />
                                            ) : unappliedPaths[path] ? (
                                                <IconUpload className="ml-1 text-warning" />
                                            ) : undefined
                                        ) : undefined
                                    if (item.data?.type === 'project') {
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
                                right={({ data, id }) =>
                                    id === 'applyPendingChanges' ? (
                                        <IconUpload className="text-warning" />
                                    ) : data?.created_at || data?.type ? (
                                        <More
                                            size="xsmall"
                                            onClick={(e) => e.stopPropagation()}
                                            overlay={
                                                <>
                                                    {data?.type === 'folder' || data?.type === 'project' ? (
                                                        <LemonButton
                                                            onClick={() => {
                                                                const folder = prompt(
                                                                    data.path
                                                                        ? `Create a folder under "${data.path}":`
                                                                        : 'Create a new folder:',
                                                                    ''
                                                                )
                                                                if (folder) {
                                                                    addFolder(
                                                                        data.path ? data.path + '/' + folder : folder
                                                                    )
                                                                }
                                                            }}
                                                            fullWidth
                                                        >
                                                            New Folder
                                                        </LemonButton>
                                                    ) : null}
                                                    {data.path ? (
                                                        <LemonButton
                                                            onClick={() => {
                                                                const oldPath = data.path
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
                                                    {data.path ? (
                                                        <LemonButton
                                                            onClick={() => {
                                                                void navigator.clipboard.writeText(data.path)
                                                            }}
                                                            fullWidth
                                                        >
                                                            Copy Path
                                                        </LemonButton>
                                                    ) : null}
                                                    {data?.created_at ? (
                                                        <LemonButton onClick={() => deleteItem(data)} fullWidth>
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
