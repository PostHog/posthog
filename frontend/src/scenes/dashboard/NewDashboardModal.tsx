import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { DialogClose, DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import { pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateChooser } from './dashboards/templates/DashboardTemplateChooser'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { dashboardTemplateVariablesLogic } from './dashboardTemplateVariablesLogic'

export function NewDashboardModal(): JSX.Element {
    const builtLogic = useMountedLogic(newDashboardLogic)
    const { hideNewDashboardModal, clearActiveDashboardTemplate, createDashboardFromTemplate } =
        useActions(newDashboardLogic)
    const { newDashboardModalVisible, activeDashboardTemplate, variableSelectModalVisible } =
        useValues(newDashboardLogic)

    const { variables } = useValues(dashboardTemplateVariablesLogic)

    const templatesLogic = dashboardTemplatesLogic({
        scope: builtLogic.props.featureFlagId ? 'feature_flag' : 'default',
    })
    const { templateFilter } = useValues(templatesLogic)
    const { setTemplateFilter } = useActions(templatesLogic)

    const title = activeDashboardTemplate ? 'Choose your events' : 'Create a dashboard'
    const description = activeDashboardTemplate ? (
        <p>
            The <i>{activeDashboardTemplate.template_name}</i> template requires you to choose{' '}
            {pluralize((activeDashboardTemplate.variables || []).length, 'event', 'events', true)}.
        </p>
    ) : (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-secondary">
                Here are some ready-made templates to help you get started quickly. Pick one below, or choose to start
                from scratch.
            </p>
            <div>
                <LemonInput
                    type="search"
                    placeholder="Filter templates"
                    onChange={setTemplateFilter}
                    value={templateFilter}
                    fullWidth={true}
                    autoFocus
                />
            </div>
        </div>
    )

    return (
        <DialogPrimitive
            open={newDashboardModalVisible}
            onOpenChange={(open) => !open && hideNewDashboardModal()}
            className={cn('w-[min(100vw-3rem,1200px)] max-h-[calc(100vh-4rem)] top-8', 'bg-surface-primary')}
        >
            <div className="flex shrink-0 flex-col gap-3 border-b border-primary px-4 py-3 pr-2">
                <div className="flex items-start justify-between gap-2">
                    <DialogPrimitiveTitle className="min-w-0 flex-1 text-base font-semibold">
                        {title}
                    </DialogPrimitiveTitle>
                    <DialogClose className="shrink-0" />
                </div>
                {description}
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden" data-attr="new-dashboard-chooser">
                <div className="NewDashboardModal overflow-y-auto p-4">
                    {activeDashboardTemplate ? (
                        <DashboardTemplateVariables />
                    ) : (
                        <DashboardTemplateChooser scope={builtLogic.props.featureFlagId ? 'feature_flag' : 'default'} />
                    )}
                </div>
            </div>
            {activeDashboardTemplate ? (
                <footer className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-primary p-4">
                    {variableSelectModalVisible ? (
                        <div />
                    ) : (
                        <LemonButton onClick={clearActiveDashboardTemplate} type="secondary">
                            Back
                        </LemonButton>
                    )}
                    <LemonButton
                        onClick={() => {
                            activeDashboardTemplate && createDashboardFromTemplate(activeDashboardTemplate, variables)
                        }}
                        type="primary"
                    >
                        Create
                    </LemonButton>
                </footer>
            ) : null}
        </DialogPrimitive>
    )
}
