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
            <FeaturePreviews focusedFeatureFlagKey={focusedFeatureFlagKey} />
        </div>
    )
}
