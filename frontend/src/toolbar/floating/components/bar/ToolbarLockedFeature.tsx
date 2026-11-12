import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ToolbarMenu } from '~/toolbar/floating/components/bar/ToolbarMenu'
import { toolbarLockedFeatureLogic } from '~/toolbar/floating/logics/toolbarLockedFeatureLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { toolbarEntitlementsLogic } from '~/toolbar/shared/toolbarEntitlementsLogic'
import { urls } from '~/toolbar/shared/urls'
import { joinWithUiHost } from '~/toolbar/shared/utils'

export interface ToolbarLockedFeatureProps {
    featureName: string
}

export function ToolbarLockedFeature({ featureName }: ToolbarLockedFeatureProps): JSX.Element {
    const { uiHost } = useValues(toolbarConfigLogic)
    const { reportViewPlansClicked } = useActions(toolbarLockedFeatureLogic({ featureName }))
    const { loadEntitlements } = useActions(toolbarEntitlementsLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Body>
                <div className="flex flex-col items-center text-center gap-2 py-4">
                    <IconLock className="text-2xl text-secondary" />
                    <h3 className="text-sm font-semibold m-0">This feature isn't in your plan</h3>
                    <p className="text-secondary m-0">
                        To use {featureName.toLowerCase()} in the toolbar, upgrade your account to pay-as-you-go.
                    </p>
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <LemonButton
                    type="secondary"
                    fullWidth
                    center
                    onClick={loadEntitlements}
                    data-attr="toolbar-locked-feature-check-again"
                >
                    Check again
                </LemonButton>
                <LemonButton
                    type="primary"
                    fullWidth
                    center
                    to={joinWithUiHost(uiHost, urls.organizationBilling())}
                    targetBlank
                    data-attr="toolbar-locked-feature-view-plans"
                    onClick={reportViewPlansClicked}
                >
                    View plans
                </LemonButton>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
