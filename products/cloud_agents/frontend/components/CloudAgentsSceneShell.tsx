import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CloudAgentsTabKey, CloudAgentsTabs } from './CloudAgentsTabs'

/** The header and the tab bar that the Runs, Presets, Usage and Settings scenes share. */
export function CloudAgentsSceneShell({
    activeTab,
    actions,
    children,
}: {
    activeTab: CloudAgentsTabKey
    actions?: JSX.Element
    children: React.ReactNode
}): JSX.Element {
    const enabled = useFeatureFlag('CLOUD_AGENTS')
    if (!enabled) {
        return <NotFound object="page" />
    }
    const config = sceneConfigurations.CloudAgents
    return (
        <SceneContent>
            <SceneTitleSection
                name={config?.name ?? 'Cloud agents'}
                description={config?.description}
                resourceType={{ type: 'cloud_agent' }}
                actions={actions}
            />
            <CloudAgentsTabs activeTab={activeTab} />
            {children}
        </SceneContent>
    )
}
