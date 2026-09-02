import type { TabData } from "@posthog/ui/features/panels/panelTypes";
import type React from "react";
import { DraggableTab } from "./DraggableTab";

interface PanelTabProps {
  tabId: string;
  panelId: string;
  label: string;
  tabData: TabData;
  isActive: boolean;
  index: number;
  draggable?: boolean;
  closeable?: boolean;
  isPreview?: boolean;
  onSelect: () => void;
  onClose?: () => void;
  onCloseOthers?: () => void;
  onCloseToRight?: () => void;
  onKeep?: () => void;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  hasUnsavedChanges?: boolean;
}

export const PanelTab: React.FC<PanelTabProps> = ({
  tabId,
  panelId,
  label,
  tabData,
  isActive,
  index,
  draggable = true,
  closeable = true,
  isPreview,
  onSelect,
  onClose,
  onCloseOthers,
  onCloseToRight,
  onKeep,
  icon,
  badge,
  hasUnsavedChanges,
}) => {
  return (
    <DraggableTab
      tabId={tabId}
      panelId={panelId}
      label={label}
      tabData={tabData}
      isActive={isActive}
      index={index}
      draggable={draggable}
      closeable={closeable}
      isPreview={isPreview}
      onSelect={onSelect}
      onClose={onClose}
      onCloseOthers={onCloseOthers}
      onCloseToRight={onCloseToRight}
      onKeep={onKeep}
      icon={icon}
      badge={badge}
      hasUnsavedChanges={hasUnsavedChanges}
    />
  );
};
