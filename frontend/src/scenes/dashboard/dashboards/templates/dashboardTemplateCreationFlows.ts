import { router } from 'kea-router'

import { UNFILED_DASHBOARDS_FOLDER } from 'scenes/dashboard/dashboardConstants'
import type { NewDashboardForm } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

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
        /** Reported as `creation_context` when the dashboard is created straight away (no variables to choose). */
        creationContext?: string
        onItemClick?: (template: DashboardTemplateType) => void
    } & DashboardTemplateClickFlowActions
): void {
    if (ctx.isLoading) {
        return
    }
    ctx.setIsLoading(true)
    const variables = template.variables ?? []
    if (variables.length === 0) {
        ctx.createDashboardFromTemplate(template, variables, ctx.redirectAfterCreation, ctx.creationContext)
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
        _create_in_folder: UNFILED_DASHBOARDS_FOLDER,
    })
}

/** Closes the templates modal and opens the New dashboard gallery, where PostHog's templates are used. */
export function openNewDashboardGallery(): void {
    const { templates: _templates, templateFilter: _templateFilter, ...searchParams } = router.values.searchParams
    router.actions.push(urls.dashboards(), searchParams, { newDashboard: 'modal' })
}
