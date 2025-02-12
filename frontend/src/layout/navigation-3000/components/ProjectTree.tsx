import { LemonButton, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'
import { useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { navigation3000Logic } from '../navigationLogic'
import { NavbarBottom } from './NavbarBottom'
import { projectTreeLogic } from './projectTreeLogic'

export function TreeView(): JSX.Element {
    const { theme } = useValues(themeLogic)
    const { isNavShown, mobileLayout } = useValues(navigation3000Logic)
    const { toggleNavCollapsed, hideNavOnMobile } = useActions(navigation3000Logic)
    const { rawProjectTree, treeData, rawProjectTreeLoading } = useValues(projectTreeLogic)
    const { addFolder, renameItem, createItem, deleteItem } = useActions(projectTreeLogic)

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
                            right={({ data }) =>
                                data?.type ? (
                                    <More
                                        size="xsmall"
                                        onClick={(e) => e.stopPropagation()}
                                        overlay={
                                            <>
                                                {data?.type === 'folder' || data?.type === 'project' ? (
                                                    <LemonButton
                                                        onClick={() => {
                                                            const folder = prompt(
                                                                'Folder name?',
                                                                (data.folder ? data.folder + '/' : '') +
                                                                    (data.name ? data.name + '/' : '')
                                                            )
                                                            if (folder) {
                                                                addFolder(folder)
                                                            }
                                                        }}
                                                        fullWidth
                                                    >
                                                        New Folder
                                                    </LemonButton>
                                                ) : null}
                                                <LemonButton
                                                    onClick={() => {
                                                        const oldPath = data.path
                                                        const folder = prompt('New name?', oldPath)
                                                        if (folder && folder !== oldPath) {
                                                            if (data.meta.custom) {
                                                                renameItem(oldPath, folder)
                                                            } else {
                                                                for (const item of rawProjectTree) {
                                                                    // find all starting with the old path in case this was a folder
                                                                    if (
                                                                        item.path === oldPath ||
                                                                        item.path.startsWith(oldPath + '/')
                                                                    ) {
                                                                        console.log({ item })
                                                                        createItem({
                                                                            ...item,
                                                                            path:
                                                                                folder +
                                                                                item.path.slice(oldPath.length),
                                                                        })
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }}
                                                    fullWidth
                                                >
                                                    Rename
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => {
                                                        void navigator.clipboard.writeText(
                                                            (data.folder ? data.folder + '/' : '') + data.name
                                                        )
                                                    }}
                                                    fullWidth
                                                >
                                                    Copy Path
                                                </LemonButton>
                                                {data?.meta?.custom ? (
                                                    <LemonButton
                                                        onClick={() => {
                                                            if (confirm('Are you sure you want to delete this item?')) {
                                                                deleteItem(data)
                                                            }
                                                        }}
                                                        fullWidth
                                                    >
                                                        Delete
                                                    </LemonButton>
                                                ) : null}
                                            </>
                                        }
                                    />
                                ) : null
                            }
                        />
                        {rawProjectTreeLoading ? <Spinner /> : null}
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
