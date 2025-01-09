import { BindLogic } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID } from './llmObservabilityLogic'

export const scene: SceneExport = {
    component: LLMObservabilityScene,
}

export function LLMObservabilityScene(): JSX.Element {
    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}>
            <div>Hello world.</div>
        </BindLogic>
    )
}
