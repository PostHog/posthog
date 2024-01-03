import { Meta } from '@storybook/react'

import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

const meta: Meta<typeof DashboardTemplateEditor> = {
    title: 'Scenes-App/Dashboards',
    component: DashboardTemplateEditor,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}
export default meta

export const CreateTemplate = (): JSX.Element => {
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
}

export const EditTemplate = (): JSX.Element => {
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
}
