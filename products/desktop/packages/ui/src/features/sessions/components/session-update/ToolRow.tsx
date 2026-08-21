import { type Icon, WrenchIcon } from "@phosphor-icons/react";
import {
  ChatMarker,
  ChatMarkerContent,
  ChatMarkerIcon,
  cn,
  Spinner,
} from "@posthog/quill";
import type { ReactNode } from "react";
import { StatusIndicators, ToolTitle } from "./toolCallUtils";

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
  /** Override the leading icon slot entirely (e.g. a caret for a group). */
  leading?: ReactNode;
  /** Extra header content after the title (e.g. a summary icon strip). */
  trailing?: ReactNode;
}

/**
 * The single wrapping element for every tool call: a ChatMarker with a header
 * (icon + text) and, when there's a body, a collapsible detail panel. Every
 * tool view and the tool-call group render through this so MCP, execute,
 * read, edit, etc. are structurally identical.
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
  leading,
  trailing,
}: ToolRowProps) {
  const isCollapsible = collapsible || content != null;

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
