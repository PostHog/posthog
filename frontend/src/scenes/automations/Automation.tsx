import './Automation.scss'
import ReactFlow, { Background, ProOptions, ReactFlowProvider } from 'reactflow'

import nodeTypes from './NodeTypes'
import edgeTypes from './EdgeTypes'

import 'reactflow/dist/style.css'
import { useActions, useValues } from 'kea'
import { automationLogic, AutomationLogicProps } from './automationLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { automationStepConfigLogic } from './AutomationStepSidebar/automationStepConfigLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { Skeleton } from 'antd'
import { NotFound } from 'lib/components/NotFound'
import { automationStepMenuLogic } from './AutomationStepSidebar/automationStepMenuLogic'
import { AutomationStepMenu } from './AutomationStepSidebar/AutomationStepMenu'
import { AutomationStepConfig } from './AutomationStepSidebar/AutomationStepConfig'

const proOptions: ProOptions = { account: 'paid-pro', hideAttribution: true }

const fitViewOptions = {
    padding: 0.95,
}

function ReactFlowPro(): JSX.Element {
    // this hook call ensures that the layout is re-calculated every time the graph changes
    const { flowSteps, flowEdges } = useValues(automationLogic)
    const { isMenuOpen } = useValues(automationStepMenuLogic)
    const { closeMenu } = useActions(automationStepMenuLogic)
    const { activeStepId } = useValues(automationStepConfigLogic)
    const { setActiveStepId } = useActions(automationStepConfigLogic)

    console.debug('flowSteps: ', flowSteps)
    console.debug('flowEdges: ', flowEdges)

    return (
        <ReactFlow
            nodes={flowSteps}
            edges={flowEdges}
            proOptions={proOptions}
            fitView
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitViewOptions={fitViewOptions}
            minZoom={1}
            maxZoom={1}
            nodesDraggable={false}
            nodesConnectable={false}
            zoomOnDoubleClick={false}
            onPaneClick={() => {
                if (isMenuOpen) {
                    closeMenu()
                }

                if (activeStepId !== null) {
                    setActiveStepId(null)
                }
            }}
        >
            <Background />
        </ReactFlow>
    )
}

export const scene: SceneExport = {
    component: Automation,
    logic: automationLogic,
    paramsToProps: ({ params: { id } }): AutomationLogicProps => ({
        automationId: id === 'new' ? 'new' : parseInt(id),
    }),
}

function Automation(): JSX.Element {
    const { activeStepId } = useValues(automationStepConfigLogic)
    const { isMenuOpen } = useValues(automationStepMenuLogic)
    const { editingExistingAutomation, automationLoading, automation, automationId } = useValues(automationLogic)
    const { setEditAutomation, loadAutomation, submitAutomation } = useActions(automationLogic)

    if (automationLoading) {
        return <Skeleton active />
    }

    if (!automation && automationId !== 'new') {
        return <NotFound object="automation" />
    }

    return (
        <div className="flex h-full">
            <div className="flex-1">
                <PageHeader
                    title={editingExistingAutomation ? 'Edit automation' : 'New automation'}
                    buttons={
                        <div className="flex items-center gap-2">
                            <LemonButton
                                data-attr="cancel-automation"
                                type="secondary"
                                onClick={() => {
                                    if (editingExistingAutomation) {
                                        setEditAutomation(false)
                                        loadAutomation()
                                    } else {
                                        router.actions.push(urls.automations())
                                    }
                                }}
                                disabled={automationLoading}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="save-automation"
                                htmlType="submit"
                                onClick={submitAutomation}
                                loading={automationLoading}
                                disabled={automationLoading}
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                />
                <LemonDivider />
                <div className="flex w-full h-full">
                    <ReactFlowProvider>
                        <ReactFlowPro />
                    </ReactFlowProvider>
                </div>
            </div>

            <div
                className={`AutomationSidebar ${!!isMenuOpen && 'AutomationSidebarInner ml-4'}`}
                style={
                    {
                        '--sidebar-width': `${isMenuOpen ? 550 : 0}px`,
                    } as React.CSSProperties
                }
            >
                <AutomationStepMenu isOpen={isMenuOpen} />
            </div>

            <div
                className={`AutomationSidebar ${!!activeStepId && 'AutomationSidebarInner ml-4'}`}
                style={
                    {
                        '--sidebar-width': `${!!activeStepId ? 550 : 0}px`,
                    } as React.CSSProperties
                }
            >
                <AutomationStepConfig isOpen={!!activeStepId} />
            </div>
        </div>
    )
}

export default Automation
