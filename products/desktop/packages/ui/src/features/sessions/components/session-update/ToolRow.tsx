import { Collapsible } from "@base-ui/react/collapsible";
import { type Icon, WrenchIcon } from "@phosphor-icons/react";
import {
  ChatMarker,
  ChatMarkerContent,
  ChatMarkerIcon,
  cn,
  Spinner,
} from "@posthog/quill";
import { type ReactNode, useState } from "react";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import {
  ExpandableIcon,
  LoadingIcon,
  StatusIndicators,
  ToolTitle,
} from "./toolCallUtils";

interface ToolRowProps {
  /** Leading tool icon. Ignored when `leading` is provided. */
  icon?: Icon;
  isLoading?: boolean;
  isFailed?: boolean;
  wasCancelled?: boolean;
  /**
   * Header content beside the icon. A plain string is wrapped in a ToolTitle;
   * pass nodes directly for richer headers (chips, mono spans, stats).
   */
  children: ReactNode;
  /** Collapsible body. When present the row becomes a collapsible trigger. */
  content?: ReactNode;
  /** Start expanded (uncontrolled). */
  defaultOpen?: boolean;
  /** Controlled open state. Provide together with `onOpenChange`. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * Force the collapsible trigger even when `content` is lazily omitted while
   * closed (used by the tool-call group, which only renders children open).
   */
  collapsible?: boolean;
  /** Wrap the content in the standard bordered box. Default true. */
  boxed?: boolean;
  /** Override the leading icon slot entirely (e.g. a caret for a group). */
  leading?: ReactNode;
  /** Extra header content after the title (e.g. a summary icon strip). */
  trailing?: ReactNode;
}

/**
 * The single wrapping element for every tool call: a header (icon + text), and
 * — when there's a body — a base-ui Collapsible whose content sits in a
 * left-padded box. Every tool view and the tool-call group render through this
 * so MCP, execute, read, edit, etc. are structurally identical.
 */
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
  collapsible,
  boxed = true,
  leading,
  trailing,
}: ToolRowProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : internalOpen;
  const setOpen = (next: boolean) => {
    if (!isControlled) setInternalOpen(next);
    onOpenChange?.(next);
  };

  const chatChrome = useChatThreadChrome();

  const isCollapsible = collapsible || content != null;

  // New thread: render the tool as a ChatMarker (icon + title row, collapsible detail body).
  // Old thread (no provider) skips this and uses the Radix chrome below.
  if (chatChrome) {
    const IconComp = icon ?? WrenchIcon;
    const iconNode = leading ?? (isLoading ? <Spinner /> : <IconComp />);
    return (
      <ChatMarker
        body={content ?? undefined}
        defaultOpen={defaultOpen}
        open={open}
        onOpenChange={onOpenChange}
        // Hover/selected chrome only when the row actually expands on click — a
        // flat marker (e.g. "Thinking" before any content arrives) shouldn't
        // invite interaction it can't honor.
        className={cn(
          "opacity-50",
          isCollapsible &&
            "hover:opacity-100 data-panel-open:bg-fill-selected data-panel-open:opacity-100",
        )}
      >
        <ChatMarkerIcon>{iconNode}</ChatMarkerIcon>
        <ChatMarkerContent className="flex w-full min-w-0 flex-nowrap items-center gap-1">
          {/* Example: posthog - insight-create(... */}
          {typeof children === "string" ? (
            <ToolTitle>{children}</ToolTitle>
          ) : (
            children
          )}
          <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
          {trailing}
        </ChatMarkerContent>
      </ChatMarker>
    );
  }

  const leadingNode = leading ?? (
    <span className="flex shrink-0 items-center justify-center pt-1">
      {isCollapsible ? (
        <ExpandableIcon
          icon={icon ?? WrenchIcon}
          isLoading={isLoading}
          isExpandable
          isExpanded={isOpen}
        />
      ) : (
        <LoadingIcon icon={icon ?? WrenchIcon} isLoading={isLoading} />
      )}
    </span>
  );

  const header = (
    <span className="flex min-w-0 flex-wrap items-center gap-1">
      {typeof children === "string" ? (
        <ToolTitle>{children}</ToolTitle>
      ) : (
        children
      )}
      <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
      {trailing}
    </span>
  );

  if (!isCollapsible) {
    return (
      <div className="group flex min-w-0 items-start gap-2 py-0.5">
        {leadingNode}
        {header}
      </div>
    );
  }

  return (
    <Collapsible.Root
      open={isOpen}
      onOpenChange={setOpen}
      className="tool-row-collapsible"
    >
      <Collapsible.Trigger className="group mb-0 flex w-full min-w-0 cursor-pointer items-start gap-2 rounded-sm py-0.5 pl-1 text-left hover:bg-fill-hover data-panel-open:bg-fill-selected">
        {leadingNode}
        {header}
      </Collapsible.Trigger>
      <Collapsible.Panel>
        {content != null && (
          <div
            className={cn(
              "flex flex-col gap-2 p-2 [&_p]:mb-0",
              boxed
                ? "mt-1 mb-3 ml-5 max-w-4xl overflow-hidden rounded-lg border border-gray-6"
                : "mt-1 ml-5",
            )}
          >
            {content}
          </div>
        )}
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}
