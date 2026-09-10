import { Box } from "@radix-ui/themes";
import type React from "react";
import { PanelResizeHandle as ResizablePanelResizeHandle } from "react-resizable-panels";

type PanelResizeHandleProps = {
  className?: string;
  style?: React.CSSProperties;
  disabled?: boolean;
  onDragging?: (isDragging: boolean) => void;
};

export const PanelResizeHandle: React.FC<PanelResizeHandleProps> = ({
  className,
  style,
  disabled,
  onDragging,
}) => {
  return (
    <ResizablePanelResizeHandle
      className={className}
      style={style}
      disabled={disabled}
      onDragging={onDragging}
    >
      <Box
        width="100%"
        height="100%"
        className="panel-resize-handle-bar bg-(--gray-6) transition-colors duration-150"
      />
    </ResizablePanelResizeHandle>
  );
};
