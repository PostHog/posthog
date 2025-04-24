import { IconCopy, IconServer } from '@posthog/icons'
import { IconArrowLeft, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DatabaseTableTree } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { Scene } from 'scenes/sceneTypes'

import { Sidebar } from '~/layout/navigation-3000/components/Sidebar'
import { SidebarNavbarItem } from '~/layout/navigation-3000/types'

import { editorSceneLogic } from '../editorSceneLogic'
import { queryDatabaseLogic } from './queryDatabaseLogic'

export const QueryDatabase = ({ isOpen }: { isOpen: boolean }): JSX.Element => {
    const navBarItem: SidebarNavbarItem = {
        identifier: Scene.SQLEditor,
        label: 'SQL editor',
        icon: <IconServer />,
        logic: editorSceneLogic,
    }

    return (
        <Sidebar navbarItem={navBarItem} sidebarOverlay={<EditorSidebarOverlay />} sidebarOverlayProps={{ isOpen }} />
    )
}
const EditorSidebarOverlay = (): JSX.Element => {
    const { setSidebarOverlayOpen } = useActions(editorSceneLogic)
    const { sidebarOverlayTreeItems, selectedSchema } = useValues(queryDatabaseLogic)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)

    const copy = (): void => {
        if (selectedSchema?.name) {
            void copyToClipboard(selectedSchema.name, 'schema')
        }
    }

    return (
        <div className="flex flex-col h-full">
            <header className="flex flex-row items-center h-10 border-b shrink-0 p-1 gap-1">
                <LemonButton size="small" icon={<IconArrowLeft />} onClick={() => setSidebarOverlayOpen(false)} />
                <Tooltip title="Click to copy">
                    <span
                        className="font-mono cursor-pointer flex-1 whitespace-nowrap overflow-hidden text-ellipsis"
                        onClick={() => copy()}
                    >
                        {selectedSchema?.name}
                    </span>
                </Tooltip>
                <div className="flex">
                    {selectedSchema?.name && (
                        <LemonButton
                            size="small"
                            icon={<IconCopy style={{ color: 'var(--text-secondary)' }} />}
                            noPadding
                            className="ml-1 mr-1"
                            data-attr="copy-icon"
                            onClick={() => copy()}
                        />
                    )}

                    {selectedSchema && 'type' in selectedSchema && selectedSchema.type !== 'managed_view' && (
                        <LemonMenu
                            items={[
                                {
                                    label: 'Add join',
                                    onClick: () => {
                                        if (selectedSchema) {
                                            selectSourceTable(selectedSchema.name)
                                            toggleJoinTableModal()
                                        }
                                    },
                                },
                            ]}
                        >
                            <div>
                                <LemonButton size="small" noPadding icon={<IconEllipsis />} />
                            </div>
                        </LemonMenu>
                    )}
                </div>
            </header>
            <div className="overflow-y-auto flex-1">
                <DatabaseTableTree items={sidebarOverlayTreeItems} />
            </div>
        </div>
    )
}
