import { RestrictToHorizontalAxis } from "@dnd-kit/abstract/modifiers";
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { Flex } from "@radix-ui/themes";
import type { ReactNode } from "react";

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
  /** Set when this pill stands for a split. `id` stays the tab whose strip
   * slot the pill takes; `label` and `icon` follow the tile that was active
   * last (`activeId`), which is where a click on the pill goes. */
  split?: SplitView;
}

export interface SplitView {
  /** The tabs that share the pane, in tile order. */
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
  onClose: (tabId: string) => void;
  /** When omitted, the trailing new-tab button is hidden. The app always passes
   * it: `+` opens the space index, which has nothing to do with what the
   * current tab is showing. */
  onNewTab?: () => void;
  onTogglePin: (tabId: string) => void;
  onCloseOthers: (tabId: string) => void;
  onCloseToRight: (tabId: string) => void;
  onCloseToLeft: (tabId: string) => void;
  /** Dissolve the split a pill stands for; every tab gets its own pill. */
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

  return (
    <TooltipProvider delay={400}>
      {/* overflow-hidden: incompressible pinned pills must clip within the
          strip rather than overlap the title bar's right-side controls.
          The container inherits the title bar's `drag` region so the empty
          space right of the pills moves the window; each interactive child
          opts out with `no-drag` individually. */}
      <Flex
        align="center"
        gap="1"
        className="h-6 min-w-0 flex-1 overflow-hidden pt-px pr-2"
        role="tablist"
      >
        {tabs.map((tab, index) => (
          <SortableTabPill
            key={tab.id}
            tab={tab}
            index={index}
            isActive={tab.id === activeTabId}
            closable={closable[index]}
            onSelect={onSelect}
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

function SortableTabPill({
  tab,
  index,
  isActive,
  closable,
  onSelect,
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
  | "onClose"
  | "onTogglePin"
  | "onCloseOthers"
  | "onCloseToRight"
  | "onCloseToLeft"
  | "onSeparate"
>) {
  // Pinned and unpinned pills sort in separate groups so a drag can't preview
  // an insertion across the pin boundary (the drop handler rejects it too).
  // Drags ride the x-axis only — the pill stays in the strip's row.
  const { ref } = useSortable({
    id: tab.id,
    index,
    group: tab.pinned ? "browser-tab-strip-pinned" : "browser-tab-strip",
    modifiers: [RestrictToHorizontalAxis],
    transition: { duration: 200, easing: "ease" },
    data: { type: "browser-tab", tabId: tab.id },
  });

  const split = tab.split;
  const closeLabel = split
    ? `Close split (${split.members.length} tabs)`
    : `Close ${tab.label}`;

  // A pinned pill collapses to icon + padding (browser-style); its label lives
  // in the tooltip. Unpinned pills keep the fading label and hover close. A
  // split pill leads with the icons of its tiles, so the strip shows which
  // pill is a split and how many pages it opens.
  const pill = (
    <div
      ref={ref}
      onAuxClick={(event) => {
        if (event.button !== 1) return;
        event.preventDefault();
        event.stopPropagation();
        onClose(tab.id);
      }}
      className={
        tab.pinned
          ? "no-drag flex shrink-0 items-center"
          : "no-drag group relative flex min-w-0 max-w-[200px] flex-1 basis-[200px] items-center overflow-hidden"
      }
    >
      <Button
        variant="default"
        size="sm"
        role="tab"
        aria-selected={isActive}
        aria-label={
          tab.pinned
            ? `${tab.label} (pinned)`
            : split
              ? `${tab.label} (split, ${split.members.length} tabs)`
              : undefined
        }
        onClick={() => onSelect(tab.id)}
        className={`h-6 px-2 ${
          tab.pinned
            ? "w-auto justify-center"
            : "w-full justify-start gap-1 transition-[padding] group-hover:pr-6"
        } ${isActive ? "" : "opacity-60 hover:opacity-100"}`}
      >
        {split ? (
          <span
            aria-hidden
            className="flex shrink-0 items-center divide-x divide-foreground/40 rounded-xs border border-foreground/40 [&_svg]:size-2"
          >
            {split.members.map((member) => (
              <span
                key={member.id}
                className="flex h-3 w-3.5 items-center justify-center"
              >
                {member.icon ?? <SplitHorizontalIcon size={8} />}
              </span>
            ))}
          </span>
        ) : tab.icon || tab.pinned ? (
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
