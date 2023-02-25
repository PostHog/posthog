import { ComponentMeta } from '@storybook/react'
import { useEffect } from 'react'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

export default {
    title: 'Scenes-App/Dashboards',
    component: DashboardTemplateEditor,
} as ComponentMeta<typeof DashboardTemplateEditor>

export const CreateTemplate = (): JSX.Element => {
    useEffect(() => {
        const unmount = dashboardTemplateEditorLogic.mount()
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
        return unmount
    }, [])

    return (
        <div className="bg-default p-4">
            <DashboardTemplateEditor inline={true} />
        </div>
    )
}

export const EditTemplate = (): JSX.Element => {
    useEffect(() => {
        const unmount = dashboardTemplateEditorLogic.mount()
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
        dashboardTemplateEditorLogic.actions.setDashboardTemplateId('123')
        return unmount
    }, [])

    return (
        <div className="bg-default p-4">
            <DashboardTemplateEditor inline={true} />
        </div>
    )
}
