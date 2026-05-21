import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AIObservabilityRenameBanner } from '../AIObservabilityRenameBanner'
import { clustersLogic } from './clustersLogic'
import { ClustersView } from './ClustersView'

export const scene: SceneExport = {
    component: AIObservabilityClustersScene,
    logic: clustersLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

export function AIObservabilityClustersScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Clusters"
                description="Discover patterns and clusters in your AI usage."
                resourceType={{ type: 'llm_clusters' }}
            />
            <AIObservabilityRenameBanner />
            <ClustersView />
        </SceneContent>
    )
}
