/**
 * JSX-based panel tree builder.
 * Use these components to declaratively define panel layouts.
 *
 * Example:
 * <PanelGroupTree direction="horizontal" sizes={[75, 25]}>
 *   <PanelLeaf>
 *     <PanelTab id="logs">{logsContent}</PanelTab>
 *   </PanelLeaf>
 *   <PanelLeaf showTabs={false}>{content}</PanelLeaf>
 * </PanelGroupTree>
 */

export interface PanelGroupTreeProps {
  direction: "horizontal" | "vertical";
  sizes?: number[];
  children: React.ReactNode;
}

export interface PanelLeafProps {
  showTabs?: boolean;
  droppable?: boolean;
  activeTabId?: string;
  children: React.ReactNode;
}

export interface PanelTabProps {
  id?: string;
  label?: string;
  icon?: React.ReactNode;
  closeable?: boolean;
  onClose?: () => void;
  onSelect?: () => void;
  children: React.ReactNode;
}

export const PanelGroupTree: React.FC<PanelGroupTreeProps> = ({ children }) => {
  return <>{children}</>;
};

export const PanelLeaf: React.FC<PanelLeafProps> = ({ children }) => {
  return <>{children}</>;
};

export const PanelTab: React.FC<PanelTabProps> = ({ children }) => {
  return <>{children}</>;
};
