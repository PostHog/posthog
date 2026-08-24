import React from "react";
import {
  type ImperativePanelGroupHandle,
  PanelGroup as ResizablePanelGroup,
} from "react-resizable-panels";

type PanelGroupProps = {
  children: React.ReactNode;
  direction: "horizontal" | "vertical";
  className?: string;
  style?: React.CSSProperties;
  autoSaveId?: string;
  onLayout?: (sizes: number[]) => void;
};

export const PanelGroup = React.forwardRef<
  ImperativePanelGroupHandle,
  PanelGroupProps
>(({ children, direction, className, style, autoSaveId, onLayout }, ref) => {
  return (
    <ResizablePanelGroup
      ref={ref}
      direction={direction}
      className={className}
      style={style}
      autoSaveId={autoSaveId}
      onLayout={onLayout}
    >
      {children}
    </ResizablePanelGroup>
  );
});

PanelGroup.displayName = "PanelGroup";
