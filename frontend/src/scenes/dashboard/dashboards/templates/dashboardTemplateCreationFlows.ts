import type { NewDashboardForm } from 'scenes/dashboard/newDashboardLogic'

import type { DashboardTemplateType, DashboardTemplateVariableType } from '~/types'

export type DashboardTemplateClickFlowActions = {
    setIsLoading: (loading: boolean) => void
    createDashboardFromTemplate: (
        template: DashboardTemplateType,
        variables: DashboardTemplateVariableType[],
        redirectAfterCreation?: boolean,
        creationContext?: string | null
    ) => void
    showVariableSelectModal: (template: DashboardTemplateType) => void
    setActiveDashboardTemplate: (template: DashboardTemplateType) => void
}

export function runDashboardTemplateClickFlow(
    template: DashboardTemplateType,
    ctx: {
        isLoading: boolean
        newDashboardModalVisible: boolean
        redirectAfterCreation: boolean
        onItemClick?: (template: DashboardTemplateType) => void
    } & DashboardTemplateClickFlowActions
): void {
    if (ctx.isLoading) {
        return
    }
    ctx.setIsLoading(true)
    const variables = template.variables ?? []
    if (variables.length === 0) {
        ctx.createDashboardFromTemplate(template, variables, ctx.redirectAfterCreation)
    } else {
        if (!ctx.newDashboardModalVisible) {
            ctx.showVariableSelectModal(template)
        } else {
            ctx.setActiveDashboardTemplate(template)
        }
    }
    ctx.onItemClick?.(template)
}

export type BlankDashboardFlowActions = {
    setIsLoading: (loading: boolean) => void
    addDashboard: (form: Partial<NewDashboardForm>) => void
}

export function runBlankDashboardFlow(ctx: { isLoading: boolean } & BlankDashboardFlowActions): void {
    if (ctx.isLoading) {
        return
    }
    ctx.setIsLoading(true)
    ctx.addDashboard({
        name: 'New Dashboard',
        show: true,
        _create_in_folder: 'Unfiled/Dashboards',
    })
}
