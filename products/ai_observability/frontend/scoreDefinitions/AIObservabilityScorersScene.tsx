import { ProductKey } from '~/queries/schema/schema-general'
import { SceneExport } from '~/scenes/sceneTypes'

import { AIObservabilityScoreDefinitions } from './AIObservabilityScoreDefinitions'
import { ScorersScene } from './ScorersScene'

export const scene: SceneExport = { component: AIObservabilityScorersScene, productKey: ProductKey.AI_OBSERVABILITY }

export function AIObservabilityScorersScene(): JSX.Element {
    return (
        <ScorersScene>
            <AIObservabilityScoreDefinitions />
        </ScorersScene>
    )
}
