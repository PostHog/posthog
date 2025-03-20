import { IconServer } from '@posthog/icons'
import { IconArrowLeft, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DatabaseTableTree } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { Scene } from 'scenes/sceneTypes'

import { Sidebar } from '~/layout/navigation-3000/components/Sidebar'
import { SidebarNavbarItem } from '~/layout/navigation-3000/types'

import { editorSceneLogic } from '../editorSceneLogic'
import { editorSidebarLogic } from '../editorSidebarLogic'

export const QueryDatabase = ({ isOpen }: { isOpen: boolean }): JSX.Element => {
    const navBarItem: SidebarNavbarItem = {
        identifier: Scene.SQLEditor,
        label: 'SQL editor',
        icon: <IconServer />,
        logic: editorSidebarLogic,
    }

    return (
        <Sidebar navbarItem={navBarItem} sidebarOverlay={<EditorSidebarOverlay />} sidebarOverlayProps={{ isOpen }} />
    )
}
const EditorSidebarOverlay = (): JSX.Element => {
    const { setSidebarOverlayOpen } = useActions(editorSceneLogic)
    const { sidebarOverlayTreeItems, selectedSchema } = useValues(editorSceneLogic)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)

    return (
        <div className="flex flex-col h-full">
            <header className="flex flex-row items-center h-10 border-b shrink-0 p-1 gap-2">
                <LemonButton size="small" icon={<IconArrowLeft />} onClick={() => setSidebarOverlayOpen(false)} />
                {selectedSchema?.name && (
                    <CopyToClipboardInline
                        className="font-mono"
                        tooltipMessage={null}
                        description="schema"
                        iconStyle={{ color: 'var(--text-secondary)' }}
                        explicitValue={selectedSchema?.name}
                    >
                        {selectedSchema?.name}
                    </CopyToClipboardInline>
                )}
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
                    <div className="absolute right-1 flex">
                        <LemonButton size="small" noPadding icon={<IconEllipsis />} />
                    </div>
                </LemonMenu>
            </header>
            <div className="overflow-y-auto flex-1">
                <DatabaseTableTree items={sidebarOverlayTreeItems} />
            </div>
        </div>
    )
}
