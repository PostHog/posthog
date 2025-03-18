import { IconBrackets, IconInfo, IconServer } from '@posthog/icons'
import { IconArrowLeft, IconEllipsis } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DatabaseTableTree } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect, useState } from 'react'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { Scene } from 'scenes/sceneTypes'

import { Sidebar } from '~/layout/navigation-3000/components/Sidebar'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { SidebarNavbarItem } from '~/layout/navigation-3000/types'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'

import { editorSceneLogic } from '../editorSceneLogic'
import { editorSidebarLogic } from '../editorSidebarLogic'
import { editorSizingLogic } from '../editorSizingLogic'
import { QueryInfo } from './QueryInfo'
import { QueryVariables } from './QueryVariables'

export const EditorSidebar = ({
    sidebarRef,
    codeEditorKey,
}: {
    sidebarRef: React.RefObject<HTMLDivElement>
    codeEditorKey: string
}): JSX.Element => {
    const { sidebarOverlayOpen } = useValues(editorSceneLogic)
    const { sidebarWidth } = useValues(editorSizingLogic)
    const { variablesForInsight } = useValues(variablesLogic)
    const { setSidebarWidth } = useActions(navigation3000Logic)
    const editorSizingLogicProps = editorSizingLogic.props

    useEffect(() => {
        setSidebarWidth(sidebarWidth)
    }, [sidebarWidth])

    // State to track active tab
    const [activeTab, setActiveTab] = useState('tab1')

    // Define tabs with icons
    const tabs = [
        {
            key: 'tab1',
            label: (
                <div className="flex justify-center px-2">
                    <IconServer className="text-xl" />
                </div>
            ),
        },
        {
            key: 'query_variables',
            label: (
                <div className="flex justify-center px-2 relative">
                    <IconBrackets className="text-xl" />
                    {variablesForInsight.length > 0 && (
                        <div className="absolute -top-1 -right-1 flex items-center justify-center bg-danger rounded-full text-white text-[9px] h-3 w-3 min-w-3">
                            {variablesForInsight.length}
                        </div>
                    )}
                </div>
            ),
        },
        {
            key: 'query_info',
            label: (
                <div className="flex justify-center px-2">
                    <IconInfo className="text-xl" />
                </div>
            ),
        },
    ]

    // Render the corresponding component based on active tab
    const renderTabContent = (): JSX.Element => {
        switch (activeTab) {
            case 'tab1':
                return <DatabaseExplorer isOpen={sidebarOverlayOpen} />
            case 'query_variables':
                return <QueryVariables />
            case 'query_info':
                return <QueryInfo codeEditorKey={codeEditorKey} />
            default:
                return <DatabaseExplorer isOpen={sidebarOverlayOpen} />
        }
    }

    return (
        <div
            className="flex flex-col h-full relative"
            ref={sidebarRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: `${sidebarWidth}px`,
            }}
        >
            <div className="border-b w-full pt-1">
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    tabs={tabs}
                    size="small"
                    barClassName="flex justify-center"
                />
            </div>
            {renderTabContent()}
            <Resizer {...editorSizingLogicProps.sidebarResizerProps} offset={0} />
        </div>
    )
}

// Tab 1 component - Database Explorer
const DatabaseExplorer = ({ isOpen }: { isOpen: boolean }): JSX.Element => {
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
