import {
  ArrowClockwise,
  ArrowLeft,
  ArrowRight,
  ArrowSquareOut,
  Code,
  Globe,
} from "@phosphor-icons/react";
import { normalizeBrowserUrl } from "@posthog/core/embedded-browser/normalizeUrl";
import type { PanelNode } from "@posthog/core/panels/panelTypes";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
} from "@posthog/quill";
import { useMutation } from "@tanstack/react-query";
import { type RefObject, useEffect, useState } from "react";
import { useCommandMenuStore } from "../../shell/commandMenuStore";
import { openExternalUrl } from "../../shell/openExternal";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { browserViewId } from "./browserViewId";
import { useEmbeddedBrowserObscuredStore } from "./embeddedBrowserObscuredStore";
import {
  type EmbeddedBrowserPageState,
  useEmbeddedBrowserPageState,
  useEmbeddedBrowserSlot,
} from "./useEmbeddedBrowser";

function isTabActiveInTree(node: PanelNode, tabId: string): boolean {
  if (node.type === "leaf") {
    return (
      node.content.activeTabId === tabId &&
      node.content.tabs.some((tab) => tab.id === tabId)
    );
  }
  return node.children.some((child) => isTabActiveInTree(child, tabId));
}

export interface BrowserPanelChromeProps {
  /** False until the tab's first navigation; shows the URL prompt. */
  hasPage: boolean;
  currentUrl: string;
  pageState: EmbeddedBrowserPageState | null;
  loadError: string | null;
  onNavigate: (rawUrl: string) => void;
  onBack: () => void;
  onForward: () => void;
  onReload: () => void;
  onOpenExternal: () => void;
  onOpenDevTools: () => void;
  /** The host glues the native browser view to this element's rect. */
  slotRef?: RefObject<HTMLDivElement | null>;
}

/**
 * The browser panel's chrome: toolbar, load-error banner, and the slot the
 * host paints the native page into. Pure — the container below owns tRPC and
 * store wiring.
 */
export function BrowserPanelChrome(props: BrowserPanelChromeProps) {
  const {
    hasPage,
    currentUrl,
    pageState,
    loadError,
    onNavigate,
    onBack,
    onForward,
    onReload,
    onOpenExternal,
    onOpenDevTools,
    slotRef,
  } = props;
  const [draftUrl, setDraftUrl] = useState<string | null>(null);

  const submitUrl = () => {
    if (draftUrl == null) return;
    const raw = draftUrl;
    setDraftUrl(null);
    onNavigate(raw);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-(--gray-6) border-b px-2 py-1.5">
        <Button
          size="icon-sm"
          aria-label="Back"
          disabled={!pageState?.canGoBack}
          onClick={onBack}
        >
          <ArrowLeft size={14} />
        </Button>
        <Button
          size="icon-sm"
          aria-label="Forward"
          disabled={!pageState?.canGoForward}
          onClick={onForward}
        >
          <ArrowRight size={14} />
        </Button>
        <Button
          size="icon-sm"
          aria-label="Reload"
          disabled={!hasPage}
          onClick={onReload}
        >
          <ArrowClockwise size={14} />
        </Button>
        <Input
          className="h-7 min-w-40 flex-1 font-mono text-xs"
          value={draftUrl ?? currentUrl}
          placeholder="Enter a URL — localhost:3000, your site…"
          // biome-ignore lint/a11y/noAutofocus: a fresh browser tab's only affordance is the URL bar, same as a browser's new-tab page.
          autoFocus={!hasPage}
          onChange={(event) => setDraftUrl(event.target.value)}
          onFocus={(event) => event.target.select()}
          onBlur={() => setDraftUrl(null)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitUrl();
            if (event.key === "Escape") setDraftUrl(null);
          }}
          aria-label="Page URL"
          spellCheck={false}
        />
        <Button
          size="icon-sm"
          aria-label="Open in external browser"
          title="Open in external browser"
          disabled={!currentUrl}
          onClick={onOpenExternal}
        >
          <ArrowSquareOut size={14} />
        </Button>
        <Button
          size="icon-sm"
          aria-label="Open DevTools"
          title="Open DevTools"
          disabled={!hasPage}
          onClick={onOpenDevTools}
        >
          <Code size={14} />
        </Button>
      </div>
      {loadError && (
        <div className="flex items-center gap-2 border-(--gray-6) border-b bg-(--red-3) px-3 py-1.5 text-(--red-11) text-xs">
          <span className="min-w-0 flex-1 truncate">{loadError}</span>
          <Button variant="outline" size="sm" onClick={onReload}>
            Retry
          </Button>
        </div>
      )}
      {/* The native browser view is glued to this slot's rect by the host. */}
      <div ref={slotRef} className="min-h-0 min-w-0 flex-1 bg-(--gray-2)">
        {!hasPage && (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Globe size={24} className="text-gray-10" />
              </EmptyMedia>
              <EmptyTitle>Open a page</EmptyTitle>
              <EmptyDescription>
                Type a URL above — your local dev server or your live site.
                Logins persist across restarts.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </div>
    </div>
  );
}

/**
 * A live browser inside a task panel, alongside Chat and Terminal. The page
 * itself is painted by a host-owned native view glued to the chrome's slot
 * div; this container wires the chrome to the host over tRPC and to the panel
 * layout store.
 */
export function BrowserPanel(props: {
  taskId: string;
  tabId: string;
  initialUrl: string;
}) {
  const { taskId, tabId, initialUrl } = props;
  const trpc = useHostTRPC();
  const viewId = browserViewId(taskId, tabId);

  // The URL the view opens with. Starts as the persisted tab URL (empty for a
  // brand-new tab); intentionally NOT synced to later prop changes — the prop
  // updates as we persist the current page, and reacting to that would loop.
  const [openUrl, setOpenUrl] = useState<string | null>(initialUrl || null);

  // Inactive tabs stay mounted with `visibility: hidden` and keep non-zero
  // rects, so "is my tab the active one" must come from the layout store —
  // the DOM cannot tell us.
  const isActiveTab = usePanelLayoutStore((state) => {
    const layout = state.taskLayouts[taskId];
    return layout ? isTabActiveInTree(layout.panelTree, tabId) : false;
  });
  // Tab drags overlay drop zones on the panel content; hide the view so they
  // are visible (and so the drag preview isn't painted over).
  const isDraggingTab = usePanelLayoutStore(
    (state) => (state.taskLayouts[taskId]?.draggingTabId ?? null) != null,
  );
  const commandMenuOpen = useCommandMenuStore((state) => state.isOpen);
  const obscuredCount = useEmbeddedBrowserObscuredStore((state) => state.count);

  const slotRef = useEmbeddedBrowserSlot({
    viewId,
    url: openUrl,
    visible:
      isActiveTab && !isDraggingTab && !commandMenuOpen && obscuredCount === 0,
  });
  const { pageState, loadError } = useEmbeddedBrowserPageState(viewId);

  const navigate = useMutation(trpc.embeddedBrowser.navigate.mutationOptions());
  const goBack = useMutation(trpc.embeddedBrowser.goBack.mutationOptions());
  const goForward = useMutation(
    trpc.embeddedBrowser.goForward.mutationOptions(),
  );
  const reload = useMutation(trpc.embeddedBrowser.reload.mutationOptions());
  const openDevTools = useMutation(
    trpc.embeddedBrowser.openDevTools.mutationOptions(),
  );

  const currentUrl = pageState?.url || openUrl || "";

  // Persist where this tab is parked (debounced) so it restores to the same
  // page after a close/reopen or app restart.
  const updateBrowserTabUrl = usePanelLayoutStore(
    (state) => state.updateBrowserTabUrl,
  );
  useEffect(() => {
    if (!pageState?.url) return;
    const handle = setTimeout(() => {
      updateBrowserTabUrl(taskId, tabId, pageState.url);
    }, 1000);
    return () => clearTimeout(handle);
  }, [pageState?.url, taskId, tabId, updateBrowserTabUrl]);

  // The tab label follows the page title, like the terminal tab follows its
  // foreground process name.
  const updateTabLabel = usePanelLayoutStore((state) => state.updateTabLabel);
  useEffect(() => {
    if (pageState?.title) updateTabLabel(taskId, tabId, pageState.title);
  }, [pageState?.title, taskId, tabId, updateTabLabel]);

  const handleNavigate = (rawUrl: string) => {
    const normalized = normalizeBrowserUrl(rawUrl);
    if (!normalized) return;
    updateBrowserTabUrl(taskId, tabId, normalized);
    if (openUrl == null) {
      // First navigation of a fresh tab: creates the view.
      setOpenUrl(normalized);
    } else if (normalized !== currentUrl) {
      navigate.mutate({ viewId, url: normalized });
    }
  };

  return (
    <BrowserPanelChrome
      hasPage={openUrl != null}
      currentUrl={currentUrl}
      pageState={pageState}
      loadError={loadError}
      onNavigate={handleNavigate}
      onBack={() => goBack.mutate({ viewId })}
      onForward={() => goForward.mutate({ viewId })}
      onReload={() => reload.mutate({ viewId })}
      onOpenExternal={() => openExternalUrl(currentUrl)}
      onOpenDevTools={() => openDevTools.mutate({ viewId })}
      slotRef={slotRef}
    />
  );
}
