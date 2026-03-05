import { useActions, useValues } from "kea";

import { LemonTag, Spinner, Tooltip } from "@posthog/lemon-ui";

import { humanFriendlyNumber } from "lib/utils";
import { SceneExport } from "scenes/sceneTypes";

import { SceneContent } from "~/layout/scenes/components/SceneContent";
import { SceneTitleSection } from "~/layout/scenes/components/SceneTitleSection";
import { ProductKey } from "~/queries/schema/schema-general";

import { NODE_TYPE_SETTINGS } from './constants'
import { NodeDetailColumns } from './NodeDetailColumns'
import { NodeDetailLineage } from './NodeDetailLineage'
import { NodeDetailLineageModal } from './NodeDetailLineageModal'
import { NodeDetailQuery } from './NodeDetailQuery'
import { NodeDetailQueryModal } from './NodeDetailQueryModal'
import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

export const scene: SceneExport<NodeDetailSceneLogicProps> = {
  component: NodeDetailScene,
  logic: nodeDetailSceneLogic,
  paramsToProps: ({ params: { id } }) => ({ id }),
  productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
};

export function NodeDetailScene({ id }: { id?: string } = {}): JSX.Element {
  const logicProps = { id: id || "" };
  const { node, nodeLoading, savedQuery, latestRowCount } = useValues(
    nodeDetailSceneLogic(logicProps),
  );
  const { updateNodeDescription } = useActions(
    nodeDetailSceneLogic(logicProps),
  );

  if (nodeLoading || !node) {
    return (
      <SceneContent>
        <div className="flex items-center justify-center py-16">
          <Spinner className="text-4xl" />
        </div>
      </SceneContent>
    );
  }

  const typeSettings = NODE_TYPE_SETTINGS[node.type];
  const hasQuery = node.type !== "table" && savedQuery?.query?.query;

  return (
    <SceneContent>
      <SceneTitleSection
        name={node.name}
        description={node.description || null}
        resourceType={{ type: "data_warehouse" }}
        isLoading={nodeLoading}
        canEdit
        saveOnBlur
        renameDebounceMs={0}
        onDescriptionChange={updateNodeDescription}
        noBorder
      />

      <div className="flex items-center gap-2 mb-2">
        <LemonTag
          style={{ backgroundColor: typeSettings.color, color: "white" }}
        >
          {typeSettings.label}
        </LemonTag>
        {latestRowCount !== null && (
          <Tooltip title="Row count from last materialization">
            <span className="text-xs text-muted">
              {humanFriendlyNumber(latestRowCount)}{" "}
              {latestRowCount === 1 ? "row" : "rows"}
            </span>
          </Tooltip>
        )}
      </div>

      <div className="space-y-6">
        {/* Query + Columns two-column layout */}
        {hasQuery ? (
          <div className="grid grid-cols-1 md:grid-cols-[3fr_2fr] gap-6">
            <NodeDetailQuery id={logicProps.id} />
            <NodeDetailColumns id={logicProps.id} />
          </div>
        ) : (
          <NodeDetailColumns id={logicProps.id} />
        )}

        {/* Lineage */}
        <NodeDetailLineage id={logicProps.id} />
            </div>

      {hasQuery && <NodeDetailQueryModal id={logicProps.id} />}
      <NodeDetailLineageModal id={logicProps.id} />
    </SceneContent>
  );
}
