import React from "react";
import type { ImperativePanelGroupHandle } from "react-resizable-panels";
import { PANEL_SIZES } from "../panelConstants";
import { calculateDefaultSize } from "../panelLayoutUtils";
import type { GroupPanel, PanelNode } from "../panelTypes";
import { Panel } from "./Panel";
import { PanelGroup } from "./PanelGroup";
import { PanelResizeHandle } from "./PanelResizeHandle";

interface GroupNodeRendererProps {
  node: GroupPanel;
  setGroupRef: (
    groupId: string,
    ref: ImperativePanelGroupHandle | null,
  ) => void;
  onLayout: (groupId: string, sizes: number[]) => void;
  renderNode: (node: PanelNode) => React.ReactNode;
}

export const GroupNodeRenderer: React.FC<GroupNodeRendererProps> = ({
  node,
  setGroupRef,
  onLayout,
  renderNode,
}) => {
  return (
    <PanelGroup
      ref={(ref) => setGroupRef(node.id, ref)}
      direction={node.direction}
      onLayout={(sizes) => onLayout(node.id, sizes)}
    >
      {node.children.map((child, index) => (
        <React.Fragment key={child.id}>
          <Panel
            id={child.id}
            order={index}
            defaultSize={calculateDefaultSize(node, index)}
            minSize={PANEL_SIZES.MIN_PANEL_SIZE}
          >
            {renderNode(child)}
          </Panel>
          {index < node.children.length - 1 && <PanelResizeHandle />}
        </React.Fragment>
      ))}
    </PanelGroup>
  );
};
