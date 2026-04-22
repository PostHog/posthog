import { useValues } from 'kea'

import { IconScreen } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardTemplateModalLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplateModalLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/** Single entry: save this dashboard as a project template (modal; staff get an optional JSON editor from there). */
export function DashboardSaveAsTemplateSceneActions(): JSX.Element | null {
    const { asDashboardTemplate, canSaveProjectDashboardTemplate } = useValues(dashboardLogic)

    const customerTemplateEditorAccess = userHasAccess(AccessControlResourceType.Dashboard, AccessControlLevel.Editor)
    const customerTemplateDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor,
        undefined,
        true
    )

    if (!canSaveProjectDashboardTemplate) {
        return null
    }

    const missingTemplatePayload = !asDashboardTemplate
    const disabled = !customerTemplateEditorAccess || missingTemplatePayload
    const tooltip = !customerTemplateEditorAccess
        ? (customerTemplateDisabledReason ?? 'You need edit access to dashboard templates to save a template.')
        : missingTemplatePayload
          ? 'Template data is not ready yet. Try again in a moment.'
          : undefined

    return (
        <ButtonPrimitive
            onClick={() => {
                if (!asDashboardTemplate) {
                    return
                }
                dashboardTemplateModalLogic.actions.openCreate(asDashboardTemplate)
            }}
            disabled={disabled}
            tooltip={tooltip}
            menuItem
            data-attr="dashboard-save-as-project-template"
        >
            <IconScreen />
            Save as dashboard template
        </ButtonPrimitive>
    )
}
