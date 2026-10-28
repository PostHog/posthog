import { type Icon, WrenchIcon } from "@phosphor-icons/react";
import {
  ChatMarker,
  ChatMarkerContent,
  ChatMarkerIcon,
  cn,
} from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import type { ReactNode } from "react";
import { StatusIndicators, ToolTitle } from "./toolCallUtils";

interface ToolRowProps {
  icon?: Icon;
  isLoading?: boolean;
  isFailed?: boolean;
  wasCancelled?: boolean;
  children: ReactNode;
  content?: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  leading?: ReactNode;
}

export function ToolRow({
  icon,
  isLoading = false,
  isFailed,
  wasCancelled,
  children,
  content,
  defaultOpen = false,
  open,
  onOpenChange,
  leading,
}: ToolRowProps) {
  const isCollapsible = content != null;
  const IconComp = icon ?? WrenchIcon;
  const iconNode = leading ?? (isLoading ? <Spinner /> : <IconComp />);

  return (
    <ChatMarker
      body={content ? <div className="pt-1.5">{content}</div> : undefined}
      defaultOpen={defaultOpen}
      open={open}
      onOpenChange={onOpenChange}
      className={cn(
        "mx-0 px-0 opacity-50 hover:bg-transparent focus-visible:bg-transparent",
        "[&_[data-slot=marker-panel]]:pt-2 [&_[data-slot=marker-panel]]:pb-1",
        "[&>svg:last-child]:ms-0",
        "focus-visible:shadow-none focus-visible:ring-(--ring)/50 focus-visible:ring-2 focus-visible:ring-inset",
        isCollapsible &&
          "hover:opacity-100 data-panel-open:bg-transparent data-panel-open:opacity-100",
        isFailed &&
          "text-destructive-foreground opacity-100 [&_*]:text-destructive-foreground",
      )}
    >
      <ChatMarkerIcon>{iconNode}</ChatMarkerIcon>
      <ChatMarkerContent className="flex min-w-0 flex-nowrap items-center gap-1 overflow-hidden">
        {typeof children === "string" ? (
          <ToolTitle>{children}</ToolTitle>
        ) : (
          children
        )}
        <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
      </ChatMarkerContent>
    </ChatMarker>
  );
}
