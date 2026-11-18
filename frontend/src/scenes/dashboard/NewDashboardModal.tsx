import { useActions, useMountedLogic, useValues } from 'kea'
import { Suspense, useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonInput, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { DialogClose, DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import { cn } from 'lib/utils/css-classes'
import { isMobile } from 'lib/utils/dom'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { pluralize } from 'lib/utils/strings'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateChooser } from 'products/dashboards/frontend/dashboards/templates/DashboardTemplateChooser'
import { dashboardTemplateChooserLogic } from 'products/dashboards/frontend/dashboards/templates/dashboardTemplateChooserLogic'
import { dashboardTemplatesLogic } from 'products/dashboards/frontend/dashboards/templates/dashboardTemplatesLogic'
import { DashboardTemplateVariables } from 'products/dashboards/frontend/DashboardTemplateVariables'
import { dashboardTemplateVariablesLogic } from 'products/dashboards/frontend/dashboardTemplateVariablesLogic'

const ObservabilityDashboardForm = lazyWithRetry(() =>
    import('products/dashboards/frontend/ObservabilityDashboardForm').then((m) => ({
        default: m.ObservabilityDashboardForm,
    }))
)

export function NewDashboardModal({ redirectAfterCreation = true }: { redirectAfterCreation?: boolean }): JSX.Element {
    const builtLogic = useMountedLogic(newDashboardLogic)
    const { hideNewDashboardModal, clearActiveDashboardTemplate, createDashboardFromTemplate } =
        useActions(newDashboardLogic)
    const { newDashboardModalVisible, activeDashboardTemplate, variableSelectModalVisible, isLoading } =
        useValues(newDashboardLogic)

    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const metricsEnabled = useFeatureFlag('METRICS')
    const metricsBuilderEnabled = useFeatureFlag('METRICS_INSIGHT_BUILDER')
    const [creationTab, setCreationTab] = useState('templates')
    const canCreateObservability =
        metricsEnabled && metricsBuilderEnabled && !builtLogic.props.featureFlagId && redirectAfterCreation
    const showObservability = canCreateObservability && creationTab === 'observability' && !activeDashboardTemplate

    useEffect(() => {
        if (!newDashboardModalVisible) {
            setCreationTab('templates')
        }
    }, [newDashboardModalVisible])

    const templateScope = builtLogic.props.featureFlagId ? 'feature_flag' : 'default'
    const templatesLogic = dashboardTemplatesLogic({ scope: templateScope })
    const { templateFilter } = useValues(templatesLogic)
    const { setTemplateFilter } = useActions(templatesLogic)

    const createChooserLogic = useMemo(
        () =>
            dashboardTemplateChooserLogic({
                scope: templateScope,
                availabilityContexts: undefined,
                redirectAfterCreation,
            }),
        [redirectAfterCreation, templateScope]
    )
    const { isLoading: blankDashboardLoading } = useValues(createChooserLogic)
    const { blankTileClicked } = useActions(createChooserLogic)

    const title = activeDashboardTemplate ? 'Choose your events' : 'Create a dashboard'
    const description = activeDashboardTemplate ? (
        <p>
            The <i>{activeDashboardTemplate.template_name}</i> template requires you to choose{' '}
            {pluralize((activeDashboardTemplate.variables || []).length, 'event', 'events', true)}.
        </p>
    ) : showObservability ? null : (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-secondary">
                Here are some ready-made templates to help you get started quickly. Pick one below or start from
                scratch.
            </p>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
                <LemonInput
                    type="search"
                    placeholder="Filter templates"
                    onChange={setTemplateFilter}
                    value={templateFilter}
                    fullWidth={true}
                    // A focused input makes iOS pan the viewport on swipe instead of scrolling the list.
                    autoFocus={!isMobile()}
                    className="min-w-0 flex-1"
                />
                <LemonButton
                    type="primary"
                    size="medium"
                    onClick={() => blankTileClicked('modal_toolbar')}
                    disabled={blankDashboardLoading}
                    data-attr="create-dashboard-blank"
                    className="shrink-0 self-start sm:self-auto"
                >
                    Start from scratch
                </LemonButton>
            </div>
        </div>
    )

    return (
        <DialogPrimitive
            // Base UI would otherwise focus the filter input on open.
            initialFocus={!isMobile()}
            open={newDashboardModalVisible}
            onOpenChange={(open) => !open && hideNewDashboardModal()}
            className={cn(
                'w-[min(100vw-3rem,1200px)] max-h-[calc(100vh-4rem)] supports-[max-height:1dvh]:max-h-[calc(100dvh-4rem)] top-8',
                'bg-surface-primary',
                // Variable selectors in ActionFilter portal to the popover layer; keep this modal just below
                // that layer so dropdown options render above the dialog instead of behind it.
                'z-[calc(var(--z-popover)-1)]'
            )}
        >
            <div className="flex shrink-0 flex-col gap-3 border-b border-primary px-4 py-3 pr-2">
                <div className="flex items-start justify-between gap-2">
                    <DialogPrimitiveTitle className="min-w-0 flex-1 text-base font-semibold">
                        {title}
                    </DialogPrimitiveTitle>
                    <DialogClose className="shrink-0" />
                </div>
                {description}
                {canCreateObservability && !activeDashboardTemplate && (
                    <LemonTabs
                        activeKey={creationTab}
                        onChange={setCreationTab}
                        tabs={[
                            { key: 'templates', label: 'Templates' },
                            { key: 'observability', label: 'Application observability' },
                        ]}
                    />
                )}
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden" data-attr="new-dashboard-chooser">
                <div className="NewDashboardModal overflow-y-auto p-4">
                    {showObservability ? (
                        <Suspense fallback={<Spinner />}>
                            <ObservabilityDashboardForm onClose={hideNewDashboardModal} />
                        </Suspense>
                    ) : activeDashboardTemplate ? (
                        <DashboardTemplateVariables />
                    ) : (
                        <DashboardTemplateChooser scope={templateScope} redirectAfterCreation={redirectAfterCreation} />
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
                            if (activeDashboardTemplate) {
                                createDashboardFromTemplate(activeDashboardTemplate, variables, redirectAfterCreation)
                            }
                        }}
                        type="primary"
                        loading={isLoading}
                        disabled={isLoading}
                    >
                        Create
                    </LemonButton>
                </footer>
            ) : null}
        </DialogPrimitive>
    )
}
