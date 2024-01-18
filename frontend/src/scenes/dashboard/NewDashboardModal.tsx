import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { pluralize } from 'lib/utils'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateChooser } from './DashboardTemplateChooser'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { dashboardTemplateVariablesLogic } from './dashboardTemplateVariablesLogic'

export function DashboardTemplatePreview(): JSX.Element {
    const { activeDashboardTemplate, variableSelectModalVisible } = useValues(newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { createDashboardFromTemplate, clearActiveDashboardTemplate } = useActions(newDashboardLogic)

    return (
        <div>
            <DashboardTemplateVariables />

            <div className="flex justify-between my-4">
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
            </div>
        </div>
    )
}

export function NewDashboardModal(): JSX.Element {
    const builtLogic = useMountedLogic(newDashboardLogic)
    const { hideNewDashboardModal } = useActions(newDashboardLogic)
    const { newDashboardModalVisible, activeDashboardTemplate } = useValues(newDashboardLogic)

    const templatesLogic = dashboardTemplatesLogic({
        scope: builtLogic.props.featureFlagId ? 'feature_flag' : 'default',
    })
    const { templateFilter } = useValues(templatesLogic)
    const { setTemplateFilter } = useActions(templatesLogic)

    const _dashboardTemplateChooser = builtLogic.props.featureFlagId ? (
        <DashboardTemplateChooser scope="feature_flag" />
    ) : (
        <DashboardTemplateChooser />
    )

    return (
        <LemonModal
            onClose={hideNewDashboardModal}
            isOpen={newDashboardModalVisible}
            title={activeDashboardTemplate ? 'Choose your events' : 'Create a dashboard'}
            description={
                activeDashboardTemplate ? (
                    <p>
                        The <i>{activeDashboardTemplate.template_name}</i> template requires you to choose{' '}
                        {pluralize((activeDashboardTemplate.variables || []).length, 'event', 'events', true)}.
                    </p>
                ) : (
                    <div className="flex flex-col gap-2">
                        <div>Choose a template or start with a blank slate</div>
                        <div>
                            <LemonInput
                                type="search"
                                placeholder="Filter templates"
                                onChange={setTemplateFilter}
                                value={templateFilter}
                                fullWidth={true}
                            />
                        </div>
                    </div>
                )
            }
        >
            <div className="NewDashboardModal">
                {activeDashboardTemplate ? <DashboardTemplatePreview /> : _dashboardTemplateChooser}
            </div>
        </LemonModal>
    )
}
