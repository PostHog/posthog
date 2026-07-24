export type PanelId = string;
export type TabId = string;
export type GroupId = string;

export type TabData =
  | {
      type: "file";
      relativePath: string;
      absolutePath: string;
      repoPath: string;
    }
  | {
      type: "terminal";
      terminalId: string;
      cwd: string;
    }
  | {
      type: "action";
      actionId: string;
      command: string;
      cwd: string;
      label: string;
    }
  | {
      type: "logs";
    }
  | {
      type: "review";
    }
  | {
      // A read-only snapshot of a channel's CONTEXT.md, shown exactly as it was
      // sent with the task's prompt (carried inline, not fetched from disk).
      type: "context";
      channelName: string | null;
      body: string;
    }
  | {
      // A read-only snapshot of the canvas generation instructions (authoring
      // contract + publishing/data rules) sent with a canvas-generation task's
      // prompt, shown exactly as the agent received them.
      type: "canvas-instructions";
      body: string;
    }
  | {
      type: "autoresearch";
    }
  | {
      type: "other";
    };

export type TabRender = unknown;

export type Tab = {
  id: TabId;
  label: string;
  data: TabData;
  component?: TabRender;
  closeable?: boolean;
  draggable?: boolean;
  onClose?: () => void;
  onSelect?: () => void;
  icon?: TabRender;
  hasUnsavedChanges?: boolean;
  badge?: TabRender;
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

export type SplitDirection = "top" | "bottom" | "left" | "right";

export interface TaskLayout {
  panelTree: PanelNode;
  openFiles: string[];
  recentFiles: string[];
  draggingTabId: string | null;
  draggingTabPanelId: string | null;
  focusedPanelId: string | null;
}
