import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { FeaturePreviews } from '~/layout/FeaturePreviews/FeaturePreviews'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelFeaturePreviews = (): JSX.Element => {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)

    const focusedFeatureFlagKey = selectedTabOptions ?? undefined

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Feature previews" />
            <div className="flex-1 p-3 overflow-y-auto deprecated-space-y-4">
                <LemonBanner type="info">
                    Get early access to these upcoming features. Let us know what you think!
                </LemonBanner>
                <FeaturePreviews focusedFeatureFlagKey={focusedFeatureFlagKey} />
            </div>
        </div>
    )
}
