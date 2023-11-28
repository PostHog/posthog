import { FeaturePreviews } from '~/layout/FeaturePreviews/FeaturePreviewsModal'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

export const SidePanelFeaturePreviews = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Feature previews" />
            <div className="flex-1 p-4 overflow-y-auto">
                <FeaturePreviews />
            </div>
        </div>
    )
}
