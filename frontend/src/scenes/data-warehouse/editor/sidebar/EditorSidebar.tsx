import { IconBolt, IconBrackets, IconServer } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'

import { editorSceneLogic } from '../editorSceneLogic'
import { editorSizingLogic } from '../editorSizingLogic'
import { editorSidebarLogic, EditorSidebarTab } from './editorSidebarLogic'
import { QueryDatabase } from './QueryDatabase'
import { QueryInfo } from './QueryInfo'
import { QueryVariables } from './QueryVariables'
import { multitabEditorLogic } from '../multitabEditorLogic'

export const EditorSidebar = ({
    sidebarRef,
    codeEditorKey,
}: {
    sidebarRef: React.RefObject<HTMLDivElement>
    codeEditorKey: string
}): JSX.Element => {
    const { sidebarOverlayOpen } = useValues(editorSceneLogic)
    const { sidebarWidth } = useValues(editorSizingLogic)
    const { setSidebarWidth } = useActions(navigation3000Logic)
    const editorSizingLogicProps = editorSizingLogic.props

    const { activeTab, variablesForInsight } = useValues(editorSidebarLogic)
    const { setActiveTab } = useActions(editorSidebarLogic)
    const { editingView } = useValues(multitabEditorLogic)

    useEffect(() => {
        setSidebarWidth(sidebarWidth)
    }, [sidebarWidth])

    const tabs = useMemo(
        () => [
            {
                key: EditorSidebarTab.QueryDatabase,
                label: (
                    <Tooltip title="Data warehouse">
                        <div className="flex justify-center px-2">
                            <IconServer className="text-xl" />
                        </div>
                    </Tooltip>
                ),
            },
            {
                key: EditorSidebarTab.QueryVariables,
                label: (
                    <Tooltip title={editingView ? 'Variables are not allowed in views.' : 'Query variables'}>
                        <div className="flex justify-center px-2 relative">
                            <IconBrackets className="text-xl" />
                            {variablesForInsight.length > 0 && (
                                <div className="absolute -top-1 -right-1 flex items-center justify-center bg-gray-700 rounded-full text-white text-[9px] h-3 w-3 min-w-3">
                                    {variablesForInsight.length}
                                </div>
                            )}
                        </div>
                    </Tooltip>
                ),
                disabled: editingView,
            },
            {
                key: EditorSidebarTab.QueryInfo,
                label: (
                    <Tooltip title="Materialization and query properties">
                        <div className="flex justify-center px-2">
                            <IconBolt className="text-xl" />
                        </div>
                    </Tooltip>
                ),
            },
        ],
        [variablesForInsight.length, editingView]
    )

    // Render the corresponding component based on active tab
    const renderTabContent = (): JSX.Element => {
        switch (activeTab) {
            case EditorSidebarTab.QueryDatabase:
                return <QueryDatabase isOpen={sidebarOverlayOpen} />
            case EditorSidebarTab.QueryVariables:
                return editingView ? (
                    <div className="px-4 py-2 text-secondary">Variables are not allowed in views.</div>
                ) : (
                    <div className="px-4 py-2">
                        <QueryVariables />
                    </div>
                )
            case EditorSidebarTab.QueryInfo:
                return (
                    <div className="px-4 py-2 overflow-y-auto">
                        <QueryInfo codeEditorKey={codeEditorKey} />
                    </div>
                )
            default:
                return <QueryDatabase isOpen={sidebarOverlayOpen} />
        }
    }

    return (
        <div
            className="EditorSidebar flex flex-col h-full relative"
            ref={sidebarRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: `${sidebarWidth}px`,
            }}
        >
            <div className="w-full">
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => {
                        posthog.capture('sql-editor-side-tab-change', { tab: key, oldTab: activeTab })
                        if (!tabs.find((t) => t.key === key && t.disabled)) {
                            setActiveTab(key)
                        }
                    }}
                    tabs={tabs}
                    size="small"
                    barClassName="flex justify-center items-center"
                />
            </div>
            {renderTabContent()}
            <Resizer {...editorSizingLogicProps.sidebarResizerProps} offset={0} />
        </div>
    )
}
