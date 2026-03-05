import { useActions, useValues } from "kea";

import { LemonTag, Spinner, Tooltip } from "@posthog/lemon-ui";

import { humanFriendlyNumber } from "lib/utils";
import { SceneExport } from "scenes/sceneTypes";

import { SceneContent } from "~/layout/scenes/components/SceneContent";
import { SceneTitleSection } from "~/layout/scenes/components/SceneTitleSection";
import { ProductKey } from "~/queries/schema/schema-general";

import { NODE_TYPE_SETTINGS } from './constants'
import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

export const scene: SceneExport<NodeDetailSceneLogicProps> = {
  component: NodeDetailScene,
  logic: nodeDetailSceneLogic,
  paramsToProps: ({ params: { id } }) => ({ id }),
  productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
};

export function NodeDetailScene({ id }: { id?: string } = {}): JSX.Element {
    const logicProps = { id: id || '' }
    const { node, nodeLoading, savedQuery, savedQueryLoading } = useValues(nodeDetailSceneLogic(logicProps))

  const typeSettings = NODE_TYPE_SETTINGS[node.type];
  const hasQuery = node.type !== "table" && savedQuery?.query?.query;

    const typeSettings = NODE_TYPE_SETTINGS[node.type]
    const isLoading = savedQueryLoading

    return (
        <SceneContent>
            <div className="space-y-4">
                <div className="flex items-center gap-3">
                    <h1 className="text-2xl font-bold mb-0">{node.name}</h1>
                    <LemonTag style={{ backgroundColor: typeSettings.color, color: 'white' }}>
                        {typeSettings.label}
                    </LemonTag>
                </div>

                {savedQuery && !isLoading && savedQuery.columns && (
                    <div className="text-secondary text-sm">
                        {savedQuery.columns.length} column{savedQuery.columns.length !== 1 ? 's' : ''}
                    </div>
                )}
            </div>
        </SceneContent>
    )
}
