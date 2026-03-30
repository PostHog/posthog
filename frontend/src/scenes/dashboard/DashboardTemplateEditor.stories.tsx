import { Meta, StoryObj } from '@storybook/react'

import { DashboardTemplateEditor, DashboardTemplateEditorProps } from './DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

const meta: Meta<DashboardTemplateEditorProps> = {
    title: 'Scenes-App/Dashboards',
    component: DashboardTemplateEditor,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}
export default meta

type Story = StoryObj<DashboardTemplateEditorProps>

export const CreateTemplate: Story = {
    render: () => {
        dashboardTemplateEditorLogic.mount()
        dashboardTemplateEditorLogic.actions.clear()
        dashboardTemplateEditorLogic.actions.openDashboardTemplateEditor()
        dashboardTemplateEditorLogic.actions.setEditorValue(
            JSON.stringify(
                {
                    id: '123',
                    template_name: 'My Template',
                },
                null,
                4
            )
        )

        return (
            <div className="bg-default p-4">
                <DashboardTemplateEditor inline={true} />
            </div>
        )
    },
}

export const EditTemplate: Story = {
    render: () => {
        dashboardTemplateEditorLogic.mount()
        dashboardTemplateEditorLogic.actions.setDashboardTemplateId('123')
        dashboardTemplateEditorLogic.actions.openDashboardTemplateEditor()
        dashboardTemplateEditorLogic.actions.setEditorValue(
            JSON.stringify(
                {
                    id: '123',
                    template_name: 'My Template',
                },
                null,
                4
            )
        )

        return (
            <div className="bg-default p-4">
                <DashboardTemplateEditor inline={true} />
            </div>
        )
    },
}
