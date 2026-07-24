import type {
  TabData as CoreTabData,
  GroupId,
  PanelId,
  SplitDirection,
  TabId,
} from "@posthog/core/panels/panelTypes";

export type { GroupId, PanelId, SplitDirection, TabId };
export type TabData = CoreTabData;

export type Tab = {
  id: TabId;
  label: string;
  data: TabData;
  component?: React.ReactNode;
  closeable?: boolean;
  draggable?: boolean;
  onClose?: () => void;
  onSelect?: () => void;
  icon?: React.ReactNode;
  hasUnsavedChanges?: boolean;
  badge?: React.ReactNode;
  isPreview?: boolean;
};

export type PanelContent = {
  id: PanelId;
  tabs: Tab[];
  activeTabId: TabId;
  showTabs?: boolean;
  droppable?: boolean;
};

export type LeafPanel = {
  type: "leaf";
  id: PanelId;
  content: PanelContent;
  size?: number;
};

export type GroupPanel = {
  type: "group";
  id: GroupId;
  direction: "horizontal" | "vertical";
  children: PanelNode[];
  sizes?: number[];
};

export type PanelNode = LeafPanel | GroupPanel;
