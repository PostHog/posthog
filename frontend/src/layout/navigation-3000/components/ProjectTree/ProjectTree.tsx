import { useDroppable } from '@dnd-kit/core'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ReactNode, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { navigation3000Logic } from '../../navigationLogic'
import { NavbarBottom } from '../NavbarBottom'
import { projectTreeLogic } from './projectTreeLogic'

export function Droppable(props: { id: string; children: ReactNode }): JSX.Element {
    const { setNodeRef } = useDroppable({ id: props.id })

    return <div ref={setNodeRef}>{props.children}</div>
}

{
    /* // renderItem={(item, children): JSX.Element => {
    //     const path = item.record?.path || ''
    //     const loading =
    //         typeof item.record?.path === 'string' || item.record?.type === 'project' ? (
    //             loadingPaths[path] ? (
    //                 <Spinner className="ml-1" />
    //             ) : unappliedPaths[path] ? (
    //                 <IconUpload className="ml-1 text-warning" />
    //             ) : undefined
    //         ) : undefined
    //     if (item.record?.type === 'project') {
    //         return (
    //             <Droppable id="">
    //                 {children}
    //                 {loading}
    //             </Droppable>
    //         )
    //     } else if (path) {
    //         return (
    //             <Droppable id={path}>
    //                 <Draggable id={path}>
    //                     {children}
    //                     {loading}
    //                 </Draggable>
    //             </Droppable>
    //         )
    //     }
    //     return (
    //         <>
    //             {children}
    //             {loading}
    //         </>
    //     )
    // }} */
}

export function ProjectTree(): JSX.Element {
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
                    <ScrollableShadows innerClassName="Navbar3000__top" direction="vertical">
                        <LemonTree
                            className="px-0 py-1"
                            data={treeData}
                            onDragEnd={(sourceId, targetId) => {
                                // console.log('Moving item:', sourceId, 'to:', targetId)

                                const oldPath = sourceId
                                const folder = targetId

                                if (folder === '') {
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
                            isItemDraggable={(item) => !!item.record?.type}
                            isItemDroppable={(item) => item.record?.type === 'folder'}
                            isItemLoading={(item) => loadingPaths[item.record?.path]}
                            isItemUnapplied={(item) => unappliedPaths[item.record?.path]}
                            itemSideAction={(item) => ({
                                icon: (
                                    <More
                                        size="xsmall"
                                        onClick={(e) => e.stopPropagation()}
                                        overlay={
                                            <>
                                                {item.record?.type === 'folder' || item.record?.type === 'project' ? (
                                                    <LemonButton
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            const folder = prompt(
                                                                item.record?.path
                                                                    ? `Create a folder under "${item.record?.path}":`
                                                                    : 'Create a new folder:',
                                                                ''
                                                            )
                                                            if (folder) {
                                                                addFolder(
                                                                    item.record?.path
                                                                        ? item.record?.path + '/' + folder
                                                                        : folder
                                                                )
                                                            }
                                                        }}
                                                        fullWidth
                                                        size="small"
                                                    >
                                                        New Folder
                                                    </LemonButton>
                                                ) : null}
                                                {item.record?.path ? (
                                                    <LemonButton
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            const oldPath = item.record?.path
                                                            const folder = prompt('New name?', oldPath)
                                                            if (folder) {
                                                                moveItem(oldPath, folder)
                                                            }
                                                        }}
                                                        fullWidth
                                                        size="small"
                                                    >
                                                        Rename
                                                    </LemonButton>
                                                ) : null}
                                                {item.record?.path ? (
                                                    <LemonButton
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            void navigator.clipboard.writeText(item.record?.path)
                                                        }}
                                                        fullWidth
                                                        size="small"
                                                    >
                                                        Copy Path
                                                    </LemonButton>
                                                ) : null}
                                                {item.record?.created_at ? (
                                                    <LemonButton
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            deleteItem(item as unknown as FileSystemEntry)
                                                        }}
                                                        fullWidth
                                                        size="small"
                                                    >
                                                        Delete
                                                    </LemonButton>
                                                ) : null}
                                            </>
                                        }
                                    />
                                ),
                                identifier: item.record?.path || 'more',
                            })}
                        />
                    </ScrollableShadows>
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
