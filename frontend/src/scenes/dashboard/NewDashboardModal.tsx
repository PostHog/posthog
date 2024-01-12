import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { pluralize } from 'lib/utils'
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
                    'Choose a template or start with a blank slate'
                )
            }
        >
            <div className="NewDashboardModal">
                {activeDashboardTemplate ? <DashboardTemplatePreview /> : _dashboardTemplateChooser}
            </div>
        </LemonModal>
    )
}
