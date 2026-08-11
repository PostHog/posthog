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
        // Overrides quill's interactive row, which bleeds its hit area 4px past
        // the text column, fills on hover, and draws an outset focus ring. All
        // three land outside the chat column here, where a transcript is mostly
        // these rows.
        className={cn(
          "mx-0 px-0 opacity-50 hover:bg-transparent focus-visible:bg-transparent",
          // quill 0.3.0-beta.24 parks the chevron at the row's far end with
          // `margin-inline-start: auto`, which strands it from the text it opens.
          "[&>svg:last-child]:ms-0",
          "focus-visible:shadow-none focus-visible:ring-(--ring)/50 focus-visible:ring-2 focus-visible:ring-inset",
          // Only rows that expand on click get the open state: a flat marker
          // ("Thinking" before any content arrives) can't honor it.
          isCollapsible &&
            "hover:opacity-100 data-panel-open:bg-transparent data-panel-open:opacity-100",
          // The descendant selector is load-bearing: the title, the argument,
          // and the status text each set their own muted color, so a color on
          // the row alone loses to all three. Scoped to the trigger so a nested
          // marker in the panel keeps its own outcome.
          isFailed &&
            "text-destructive-foreground opacity-100 [&_*]:text-destructive-foreground",
        )}
      >
        <ChatMarkerIcon>{iconNode}</ChatMarkerIcon>
        {/* No `w-full`: the content sizes to its text, so the chevron sits
            against the end of it. `overflow-hidden` keeps a long argument from
            spilling past the trigger. */}
        <ChatMarkerContent className="flex min-w-0 flex-nowrap items-center gap-1 overflow-hidden">
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
