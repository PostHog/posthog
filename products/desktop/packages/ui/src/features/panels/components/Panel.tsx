import React from "react";
import {
  type ImperativePanelHandle,
  Panel as ResizablePanel,
} from "react-resizable-panels";

type PanelProps = {
  children: React.ReactNode;
  id?: string;
  order?: number;
  className?: string;
  style?: React.CSSProperties;
  defaultSize?: number;
  minSize?: number;
  maxSize?: number;
  collapsible?: boolean;
  collapsedSize?: number;
  onCollapse?: () => void;
  onResize?: (size: number, prevSize: number | undefined) => void;
};

export const Panel = React.forwardRef<ImperativePanelHandle, PanelProps>(
  (
    {
      children,
      id,
      order,
      className,
      style,
      defaultSize,
      minSize,
      maxSize,
      collapsible,
      collapsedSize,
      onCollapse,
      onResize,
    },
    ref,
  ) => {
    return (
      <ResizablePanel
        ref={ref}
        id={id}
        order={order}
        className={className}
        style={style}
        defaultSize={defaultSize}
        minSize={minSize}
        maxSize={maxSize}
        collapsible={collapsible}
        collapsedSize={collapsedSize}
        onCollapse={onCollapse}
        onResize={onResize}
      >
        {children}
      </ResizablePanel>
    );
  },
);

Panel.displayName = "Panel";
