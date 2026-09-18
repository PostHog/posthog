import { useDroppable } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import {
  PlusIcon,
  PushPinIcon,
  SplitHorizontalIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
  cn,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { Flex } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { STRIP_DROP_TYPE, type StripDropData } from "./stripDrop";
import { DetachFromStrip } from "./tabDetach";
import { useTabReorderStore } from "./tabReorderStore";

export interface TabView {
  id: string;
  label: string;
  /** Optional leading icon (template-derived, or a session's status dot). */
  icon?: ReactNode;
  /** Channel the tab belongs to; shown `#`-prefixed atop the hover. Null = no
   * channel (a blank tab). */
  channelName?: string | null;
  /** True for a channel's index page — the hover reads `#channel / home`. */
  isChannelHome?: boolean;
  /** Pinned tabs collapse to icon-only, sort first, and survive bulk closes. */
  pinned?: boolean;
  split?: SplitView;
}

export interface SplitView {
  members: SplitMember[];
  activeId: string;
}

export interface SplitMember {
  id: string;
  label: string;
  icon?: ReactNode;
}

/** Which bulk-close actions would close at least one (unpinned) tab. */
interface Closable {
  others: boolean;
  left: boolean;
  right: boolean;
}

export interface TabStripProps {
  tabs: TabView[];
  activeTabId: string | null;
  onSelect: (tabId: string) => void;
  onSelectMember: (tabId: string) => void;
  onClose: (tabId: string) => void;
  /** When omitted, the trailing new-tab button is hidden. The app always passes
   * it: `+` opens the space index, which has nothing to do with what the
   * current tab is showing. */
  onNewTab?: () => void;
  onTogglePin: (tabId: string) => void;
  onCloseOthers: (tabId: string) => void;
  onCloseToRight: (tabId: string) => void;
  onCloseToLeft: (tabId: string) => void;
  onSeparate: (tabId: string) => void;
}

/**
 * Presentational title-bar tab strip: pill tabs (active elevated/white,
 * inactive muted) with an optional icon + label and a hover-revealed close,
 * plus a trailing new-tab button. Right-click opens a context menu with pin
 * and bulk-close actions; pills drag to reorder (BrowserTabsDndProvider must
 * be an ancestor). All state and resolution is supplied by the container.
 */
export function TabStrip({
  tabs,
  activeTabId,
  onSelect,
  onSelectMember,
  onClose,
  onNewTab,
  onTogglePin,
  onCloseOthers,
  onCloseToRight,
  onCloseToLeft,
  onSeparate,
}: TabStripProps) {
  // Which bulk closes are live per pill, in a single pass over the strip
  // (each closes only *unpinned* tabs in its range).
  const unpinnedTotal = tabs.reduce((n, t) => n + (t.pinned ? 0 : 1), 0);
  let unpinnedBefore = 0;
  const closable: Closable[] = tabs.map((t) => {
    const self = t.pinned ? 0 : 1;
    const c: Closable = {
      others: unpinnedTotal - self > 0,
      left: unpinnedBefore > 0,
      right: unpinnedTotal - unpinnedBefore - self > 0,
    };
    unpinnedBefore += self;
    return c;
  });

  const tileDragActive = useTabReorderStore((s) => s.dragSource === "tile");
  const stripDropData: StripDropData = { type: STRIP_DROP_TYPE };
  const { ref: stripRef, isDropTarget } = useDroppable({
    id: "browser-tab-strip",
    data: stripDropData,
    disabled: !tileDragActive,
  });

  return (
    <TooltipProvider delay={400}>
      {/* overflow-hidden: incompressible pinned pills must clip within the
          strip rather than overlap the title bar's right-side controls.
          The container inherits the title bar's `drag` region so the empty
          space right of the pills moves the window; each interactive child
          opts out with `no-drag` individually. */}
      <Flex
        ref={stripRef}
        align="center"
        gap="1"
        className={cn(
          "h-6 min-w-0 flex-1 overflow-hidden pt-px pr-2",
          isDropTarget && "rounded-md ring-1 ring-accent-8",
        )}
        role="tablist"
      >
        {tabs.map((tab, index) => (
          <SortableTabPill
            key={tab.id}
            tab={tab}
            index={index}
            isActive={(tab.split?.activeId ?? tab.id) === activeTabId}
            closable={closable[index]}
            onSelect={onSelect}
            onSelectMember={onSelectMember}
            onClose={onClose}
            onTogglePin={onTogglePin}
            onCloseOthers={onCloseOthers}
            onCloseToRight={onCloseToRight}
            onCloseToLeft={onCloseToLeft}
            onSeparate={onSeparate}
          />
        ))}
        {onNewTab && (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="icon-sm"
                  aria-label="New tab"
                  className="no-drag shrink-0"
                  onClick={onNewTab}
                >
                  <PlusIcon size={14} />
                </Button>
              }
            />
            <TooltipContent side="bottom">New tab</TooltipContent>
          </Tooltip>
        )}
      </Flex>
    </TooltipProvider>
  );
}

function SplitPill({
  tab,
  split,
  isActive,
  onSelectMember,
}: {
  tab: TabView;
  split: SplitView;
  isActive: boolean;
  onSelectMember: (tabId: string) => void;
}) {
  const labelEvery = split.members.length <= 2;
  return (
    <div
      role="tab"
      tabIndex={-1}
      aria-selected={isActive}
      aria-label={`${tab.label} (split, ${split.members.length} tabs)`}
      className={cn(
        "flex h-6 w-full items-stretch overflow-hidden rounded-md bg-muted ring-1 ring-border ring-inset transition-[padding] group-hover:pr-5",
        !isActive && "opacity-60 hover:opacity-100",
      )}
    >
      {split.members.map((member, index) => {
        const shown = member.id === split.activeId;
        const labelled = labelEvery || shown;
        return (
          <button
            key={member.id}
            type="button"
            title={member.label}
            aria-current={shown && isActive ? "true" : undefined}
            onClick={() => onSelectMember(member.id)}
            className={cn(
              "flex min-w-0 items-center gap-1 text-xs transition-colors",
              index > 0 && "border-border border-l",
              labelled ? "flex-1 justify-start px-1.5" : "w-7 justify-center",
              shown
                ? "bg-background font-medium shadow-xs"
                : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
            )}
          >
            <span className="flex shrink-0 items-center [&>svg]:size-3">
              {member.icon ?? <SplitHorizontalIcon size={12} />}
            </span>
            {labelled && (
              <span className="min-w-0 flex-1 overflow-hidden whitespace-nowrap text-left [-webkit-mask-image:linear-gradient(to_right,#000,#000_calc(100%-0.75rem),#0000)] [mask-image:linear-gradient(to_right,#000,#000_calc(100%-0.75rem),#0000)]">
                {member.label}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function SortableTabPill({
  tab,
  index,
  isActive,
  closable,
  onSelect,
  onSelectMember,
  onClose,
  onTogglePin,
  onCloseOthers,
  onCloseToRight,
  onCloseToLeft,
  onSeparate,
}: {
  tab: TabView;
  index: number;
  isActive: boolean;
  closable: Closable;
} & Pick<
  TabStripProps,
  | "onSelect"
  | "onSelectMember"
  | "onClose"
  | "onTogglePin"
  | "onCloseOthers"
  | "onCloseToRight"
  | "onCloseToLeft"
  | "onSeparate"
>) {
  // Pinned and unpinned pills sort in separate groups so a drag can't preview
  // an insertion across the pin boundary (the drop handler rejects it too).
  const { ref, isDragSource } = useSortable({
    id: tab.id,
    index,
    group: tab.pinned ? "browser-tab-strip-pinned" : "browser-tab-strip",
    modifiers: [DetachFromStrip],
    transition: { duration: 200, easing: "ease" },
    data: { type: "browser-tab", tabId: tab.id },
  });
  const detached = useTabReorderStore((s) => isDragSource && s.detached);

  const split = tab.split;
  const closeLabel = split
    ? `Close split (${split.members.length} tabs)`
    : `Close ${tab.label}`;

  // A pinned pill collapses to icon + padding (browser-style); its label lives
  // in the tooltip. Unpinned pills keep the fading label and hover close.
  const pill = (
    <div
      ref={ref}
      onAuxClick={(event) => {
        if (event.button !== 1) return;
        event.preventDefault();
        event.stopPropagation();
        onClose(tab.id);
      }}
      className={cn(
        tab.pinned
          ? "no-drag flex shrink-0 items-center"
          : split
            ? "no-drag group relative flex min-w-0 max-w-[340px] flex-1 basis-[340px] items-center overflow-hidden"
            : "no-drag group relative flex min-w-0 max-w-[200px] flex-1 basis-[200px] items-center overflow-hidden",
        detached && "rounded-md bg-background shadow-lg ring-1 ring-border",
      )}
    >
      {split ? (
        <SplitPill
          tab={tab}
          split={split}
          isActive={isActive}
          onSelectMember={onSelectMember}
        />
      ) : (
        <Button
          variant="default"
          size="sm"
          role="tab"
          aria-selected={isActive}
          aria-label={tab.pinned ? `${tab.label} (pinned)` : undefined}
          onClick={() => onSelect(tab.id)}
          className={`h-6 px-2 ${
            tab.pinned
              ? "w-auto justify-center"
              : "w-full justify-start gap-1 transition-[padding] group-hover:pr-6"
          } ${isActive ? "" : "opacity-60 hover:opacity-100"}`}
        >
          {tab.icon || tab.pinned ? (
            <span className="flex shrink-0 items-center [&>svg]:size-3.5">
              {tab.icon ?? <PushPinIcon size={14} weight="fill" />}
            </span>
          ) : null}
          {/* Fade the right edge instead of an ellipsis; the label shrinks on
            hover (button gets pr) so the fade follows, clearing room for the
            close button. */}
          {tab.pinned ? null : (
            <span className="min-w-0 flex-1 overflow-hidden whitespace-nowrap text-left [-webkit-mask-image:linear-gradient(to_right,#000,#000_calc(100%-0.75rem),#0000)] [mask-image:linear-gradient(to_right,#000,#000_calc(100%-0.75rem),#0000)]">
              {tab.label}
            </span>
          )}
        </Button>
      )}
      {tab.pinned ? null : (
        <button
          type="button"
          aria-label={closeLabel}
          onClick={(e) => {
            e.stopPropagation();
            onClose(tab.id);
          }}
          className="-translate-y-1/2 absolute top-1/2 right-1 flex size-4 items-center justify-center rounded-sm opacity-0 transition-opacity hover:bg-muted group-hover:opacity-100"
        >
          <XIcon size={12} />
        </button>
      )}
    </div>
  );

  return (
    <ContextMenu>
      <Tooltip>
        <TooltipTrigger render={<ContextMenuTrigger render={pill} />} />
        {/* `flex-col items-start`: TooltipContent is a centred ROW by default,
            which laid the two lines side by side and wrapped both. They stack,
            and each stays on one line — a tooltip that exists to show a
            truncated name must not truncate it again by wrapping. */}
        <TooltipContent
          side="bottom"
          className="flex-col items-start gap-0 whitespace-nowrap"
        >
          {/* Channel context first (always `#`-prefixed); the channel-home tab
              reads `#channel / home`. Then the page name, unless it would just
              repeat the channel-home name already shown above. */}
          {tab.channelName ? (
            <div className="text-muted">
              {tab.channelName}
              {tab.isChannelHome ? " / home" : null}
            </div>
          ) : null}
          {split ? (
            <>
              <div className="text-muted">Split view</div>
              {split.members.map((member) => (
                <div
                  key={member.id}
                  className={
                    member.id === split.activeId ? "font-medium" : undefined
                  }
                >
                  {member.label}
                </div>
              ))}
            </>
          ) : tab.label && !(tab.isChannelHome && tab.channelName) ? (
            <div className="font-medium">{tab.label}</div>
          ) : null}
        </TooltipContent>
      </Tooltip>
      {/* no-drag: the menu opens under the title bar's drag region, and
          Electron drag regions swallow clicks on anything visually
          overlapping them — even a portalled popup on top. */}
      <ContextMenuContent className="no-drag">
        {split ? (
          <ContextMenuItem onClick={() => onSeparate(tab.id)}>
            <SplitHorizontalIcon size={14} />
            Separate all tabs
          </ContextMenuItem>
        ) : (
          <ContextMenuItem onClick={() => onTogglePin(tab.id)}>
            <PushPinIcon size={14} />
            {tab.pinned ? "Unpin tab" : "Pin tab"}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem onClick={() => onClose(tab.id)}>
          <XIcon size={14} />
          {split ? "Close split" : "Close tab"}
        </ContextMenuItem>
        <ContextMenuItem
          inset
          disabled={!closable.others}
          onClick={() => onCloseOthers(tab.id)}
        >
          Close other tabs
        </ContextMenuItem>
        <ContextMenuItem
          inset
          disabled={!closable.right}
          onClick={() => onCloseToRight(tab.id)}
        >
          Close tabs to the right
        </ContextMenuItem>
        <ContextMenuItem
          inset
          disabled={!closable.left}
          onClick={() => onCloseToLeft(tab.id)}
        >
          Close tabs to the left
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
