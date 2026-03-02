import { Menu } from '@base-ui/react/menu'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconFolder } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { MenuTrigger } from '~/layout/panel-layout/ai-first/MenuTrigger'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

const FILES_MENU_LOGIC_KEY = 'files-menu'

function FilesSearchInput(): JSX.Element {
    const { searchTerm } = useValues(projectTreeLogic)
    const { setSearchTerm, clearSearch } = useActions(projectTreeLogic)
    const inputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const timer = setTimeout(() => inputRef.current?.focus(), 0)
        return () => clearTimeout(timer)
    }, [])

    return (
        <input
            ref={inputRef}
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={(e) => {
                if (e.key === 'Escape' && searchTerm) {
                    e.stopPropagation()
                    clearSearch()
                } else if (e.key !== 'Escape' && e.key !== 'Tab') {
                    e.stopPropagation()
                }
            }}
            placeholder="Search files"
            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
        />
    )
}

function FilesMenuContent(): JSX.Element {
    const logicProps = { key: FILES_MENU_LOGIC_KEY, root: 'project://' }

    return (
        <>
            <BindLogic logic={projectTreeLogic} props={logicProps}>
                <FilesSearchInput />
            </BindLogic>
            <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                <ProjectTree logicKey={FILES_MENU_LOGIC_KEY} root="project://" onlyTree />
            </ScrollableShadows>
        </>
    )
}

export function FilesMenu({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    return (
        <Menu.Root>
            <MenuTrigger label="Files" icon={<IconFolder />} isCollapsed={isCollapsed} />
            <Menu.Portal keepMounted>
                <Menu.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Menu.Popup className="primitive-menu-content min-w-[300px] flex flex-col p-1 h-(--available-height)">
                        <FilesMenuContent />
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
