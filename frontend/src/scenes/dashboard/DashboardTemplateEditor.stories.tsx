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
        dashboardTemplateEditorLogic.mount()
        dashboardTemplateEditorLogic.actions.setOpenNewDashboardTemplateModal(true)
        dashboardTemplateEditorLogic.actions.setDashboardTemplateJSON(
            JSON.stringify(
                {
                    id: '123',
                    template_name: 'My Template',
                },
                null,
                4
            )
        )
    }, [])

    return (
        <div className="bg-default p-4">
            <DashboardTemplateEditor inline={true} />
        </div>
    )
}

export const EditTemplate = (): JSX.Element => {
    useEffect(() => {
        dashboardTemplateEditorLogic.mount()
        dashboardTemplateEditorLogic.actions.setOpenNewDashboardTemplateModal(true)
        dashboardTemplateEditorLogic.actions.setDashboardTemplateJSON(
            JSON.stringify(
                {
                    id: '123',
                    template_name: 'My Template',
                },
                null,
                4
            )
        )
        dashboardTemplateEditorLogic.actions.setDashboardTemplateId('123') // TODO: work out how to only have this action apply to this one story
    }, [])

    return (
        <div className="bg-default p-4">
            <DashboardTemplateEditor inline={true} />
        </div>
    )
}
