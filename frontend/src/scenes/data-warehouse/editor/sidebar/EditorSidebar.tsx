import { IconBolt, IconBrackets, IconInfo, IconServer } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect, useRef, useState } from 'react'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'

import { editorSceneLogic } from '../editorSceneLogic'
import { editorSizingLogic } from '../editorSizingLogic'
import { Materialization } from './Materialization'
import { QueryDatabase } from './QueryDatabase'
import { QueryInfo } from './QueryInfo'
import { QueryVariables } from './QueryVariables'

enum EditorSidebarTab {
    QueryDatabase = 'query_database',
    QueryVariables = 'query_variables',
    QueryInfo = 'query_info',
    Materialization = 'materialization',
}

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
    const [activeTab, setActiveTab] = useState(EditorSidebarTab.QueryDatabase)
    const prevLengthRef = useRef(0)

    useEffect(() => {
        if (variablesForInsight.length > prevLengthRef.current) {
            setActiveTab(EditorSidebarTab.QueryVariables)
        }
        prevLengthRef.current = variablesForInsight.length
    }, [variablesForInsight])

    // Define tabs with icons
    const tabs = [
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
                <Tooltip title="Query variables">
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
        },
        {
            key: EditorSidebarTab.Materialization,
            label: (
                <Tooltip title="Materialization">
                    <div className="flex justify-center px-2">
                        <IconBolt className="text-xl" />
                    </div>
                </Tooltip>
            ),
        },
        {
            key: EditorSidebarTab.QueryInfo,
            label: (
                <Tooltip title="Query properties">
                    <div className="flex justify-center px-2">
                        <IconInfo className="text-xl" />
                    </div>
                </Tooltip>
            ),
        },
    ]

    // Render the corresponding component based on active tab
    const renderTabContent = (): JSX.Element => {
        switch (activeTab) {
            case EditorSidebarTab.QueryDatabase:
                return <QueryDatabase isOpen={sidebarOverlayOpen} />
            case EditorSidebarTab.QueryVariables:
                return <QueryVariables />
            case EditorSidebarTab.Materialization:
                return <Materialization />
            case EditorSidebarTab.QueryInfo:
                return <QueryInfo codeEditorKey={codeEditorKey} />
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
                    onChange={setActiveTab}
                    tabs={tabs}
                    size="small"
                    barClassName="flex justify-center h-10 items-center"
                />
            </div>
            {renderTabContent()}
            <Resizer {...editorSizingLogicProps.sidebarResizerProps} offset={0} />
        </div>
    )
}
