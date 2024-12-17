import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { AlphaAccessScenePrompt } from './AlphaAccessScenePrompt'
import Alerts from './configuration/Alerts'
import { errorTrackingSymbolSetLogic } from './configuration/errorTrackingSymbolSetLogic'
import SymbolSets from './configuration/SymbolSets'
import { ConfigurationTab, errorTrackingConfigurationSceneLogic } from './errorTrackingConfigurationSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingSymbolSetLogic,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    const { tab } = useValues(errorTrackingConfigurationSceneLogic)
    const { setTab } = useActions(errorTrackingConfigurationSceneLogic)

    return (
        <AlphaAccessScenePrompt>
            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    { label: 'Alerts', key: ConfigurationTab.Alerts, content: <Alerts /> },
                    { label: 'Symbol sets', key: ConfigurationTab.SymbolSets, content: <SymbolSets /> },
                ]}
            />
        </AlphaAccessScenePrompt>
    )
}
