import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { toolbarLockedFeatureLogic } from '~/toolbar/bar/toolbarLockedFeatureLogic'
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { urls } from '~/toolbar/urls'
import { joinWithUiHost } from '~/toolbar/utils'

export interface ToolbarLockedFeatureProps {
    featureName: string
}

export function ToolbarLockedFeature({ featureName }: ToolbarLockedFeatureProps): JSX.Element {
    const { uiHost } = useValues(toolbarConfigLogic)
    const { reportViewPlansClicked } = useActions(toolbarLockedFeatureLogic({ featureName }))

    return (
        <ToolbarMenu>
            <ToolbarMenu.Body>
                <div className="flex flex-col items-center text-center gap-2 py-4">
                    <IconLock className="text-2xl text-secondary" />
                    <h3 className="text-sm font-semibold m-0">This feature isn't in your plan</h3>
                    <p className="text-secondary m-0">
                        To use {featureName.toLowerCase()} in the toolbar, choose a plan that includes it.
                    </p>
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
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
