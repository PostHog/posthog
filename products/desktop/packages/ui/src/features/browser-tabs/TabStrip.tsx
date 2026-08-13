import { RestrictToHorizontalAxis } from "@dnd-kit/abstract/modifiers";
import { useSortable } from "@dnd-kit/react/sortable";
import { PlusIcon, PushPinIcon, XIcon } from "@phosphor-icons/react";
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
  /** Optional leading icon (template-derived). */
  icon?: ReactNode;
  /** Channel the tab belongs to; shown `#`-prefixed atop the hover. Null = no
   * channel (a blank tab). */
  channelName?: string | null;
  /** True for a channel's index page — the hover reads `#channel / home`. */
  isChannelHome?: boolean;
  /** Pinned tabs collapse to icon-only, sort first, and survive bulk closes. */
  pinned?: boolean;
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
  /** When omitted, the trailing new-tab button is hidden (e.g. on read-only
   * cloud runs, where opening a tab makes no sense). */
  onNewTab?: () => void;
  onTogglePin: (tabId: string) => void;
  onCloseOthers: (tabId: string) => void;
  onCloseToRight: (tabId: string) => void;
  onCloseToLeft: (tabId: string) => void;
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

  // A pinned pill collapses to icon + padding (browser-style); its label lives
  // in the tooltip. Unpinned pills keep the fading label and hover close.
  const pill = (
    <div
      ref={ref}
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
      {tab.pinned ? null : (
        <button
          type="button"
          aria-label={`Close ${tab.label}`}
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
        <TooltipContent side="bottom">
          {/* Channel context first (always `#`-prefixed); the channel-home tab
              reads `#channel / home`. Then the page name, unless it would just
              repeat the channel-home name already shown above. */}
          {tab.channelName ? (
            <div className="text-muted">
              {tab.channelName}
              {tab.isChannelHome ? " / home" : null}
            </div>
          ) : null}
          {tab.label && !(tab.isChannelHome && tab.channelName) ? (
            <div className="font-medium">{tab.label}</div>
          ) : null}
        </TooltipContent>
      </Tooltip>
      {/* no-drag: the menu opens under the title bar's drag region, and
          Electron drag regions swallow clicks on anything visually
          overlapping them — even a portalled popup on top. */}
      <ContextMenuContent className="no-drag">
        <ContextMenuItem onClick={() => onTogglePin(tab.id)}>
          <PushPinIcon size={14} />
          {tab.pinned ? "Unpin tab" : "Pin tab"}
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onClick={() => onClose(tab.id)}>
          <XIcon size={14} />
          Close tab
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
