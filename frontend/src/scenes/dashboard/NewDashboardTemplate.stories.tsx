import { ComponentMeta } from '@storybook/react'
import { useEffect } from 'react'
import { NewDashboardTemplate } from './NewDashboardTemplate'
import { newDashboardTemplateLogic } from './NewDashboardTemplateLogic'

export default {
    title: 'Dashboard/NewTemplate',
    component: NewDashboardTemplate,
} as ComponentMeta<typeof NewDashboardTemplate>

export const NewTemplate = (): JSX.Element => {
    useEffect(() => {
        newDashboardTemplateLogic.mount()
        newDashboardTemplateLogic.actions.setOpenNewDashboardTemplateModal(true)
        newDashboardTemplateLogic.actions.setDashboardTemplateJSON(
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
            <NewDashboardTemplate inline={true} />
        </div>
    )
}
