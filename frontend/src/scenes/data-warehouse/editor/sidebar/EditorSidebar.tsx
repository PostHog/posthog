import { IconBrackets, IconInfo, IconServer } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect, useState } from 'react'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'

import { editorSceneLogic } from '../editorSceneLogic'
import { editorSizingLogic } from '../editorSizingLogic'
import { QueryDatabase } from './QueryDatabase'
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
    const [activeTab, setActiveTab] = useState('query_database')

    // Define tabs with icons
    const tabs = [
        {
            key: 'query_database',
            label: (
                <Tooltip title="Data warehouse">
                    <div className="flex justify-center px-2">
                        <IconServer className="text-xl" />
                    </div>
                </Tooltip>
            ),
        },
        {
            key: 'query_variables',
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
            key: 'query_info',
            label: (
                <Tooltip title="Materialization and query properties">
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
            case 'query_database':
                return <QueryDatabase isOpen={sidebarOverlayOpen} />
            case 'query_variables':
                return <QueryVariables />
            case 'query_info':
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
