import { LemonBanner } from '@posthog/lemon-ui'

import { FeaturePreviews } from '~/layout/FeaturePreviews/FeaturePreviews'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

export const SidePanelFeaturePreviews = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Feature previews" />
            <div className="flex-1 p-4 overflow-y-auto space-y-4">
                <LemonBanner type="info">
                    Get early access to these upcoming features. Let us know what you think!
                </LemonBanner>
                <FeaturePreviews />
            </div>
        </div>
    )
}
