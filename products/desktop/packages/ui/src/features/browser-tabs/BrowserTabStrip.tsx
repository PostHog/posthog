import {
  BrainIcon,
  HashIcon,
  PlugsConnectedIcon,
  RobotIcon,
  SquaresFourIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  closeTab as closeTabLocal,
  closeTabs as closeTabsLocal,
  decideTabNavigation,
  newBlankTab as newBlankTabLocal,
  openOrFocusTab as openOrFocusLocal,
  PROJECT_BLUEBIRD_FLAG,
  primaryWindow,
  setTabOrder,
  setTabTarget as setTabTargetLocal,
  setWindowActiveTab,
  type TabsSnapshot,
} from "@posthog/shared";
import { channelSectionFor } from "@posthog/ui/features/canvas/channelSections";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { ensurePersonalChannel } from "@posthog/ui/features/canvas/ensurePersonalChannel";
import {
  useChannelMutations,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  useDashboard,
  useDashboards,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { getLeafPanel } from "@posthog/ui/features/panels/panelStoreHelpers";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useIsWorkspaceCloudRun } from "@posthog/ui/features/workspace/useWorkspace";
import { useAppView } from "@posthog/ui/router/useAppView";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  useNavigate,
  useParams,
  useRouter,
  useRouterState,
} from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import {
  frontOfUnpinnedOrder,
  partitionPinnedFirst,
  storedOrderIds,
} from "./displayOrder";
import { usePinnedTabsStore } from "./pinnedTabsStore";
import { TabStrip, type TabView } from "./TabStrip";
import { TaskTabIcon } from "./TaskTabIcon";
import { useTabReorderStore } from "./tabReorderStore";
import {
  applyLocalTransform,
  persistWrite,
  readMirror,
  reseedMirror,
} from "./tabsSync";
import { useTabsSnapshot } from "./useBrowserTabs";

/** The active tab id is carried in router history state so back/forward replay
 * tab switches. */
declare module "@tanstack/history" {
  interface HistoryState {
    tabId?: string;
  }
}

/**
 * Module-level caches of display info, keyed by id. Tabs store only references;
 * names are resolved here as the user navigates (which loads each channel's
 * canvases/tasks), so cross-channel tabs still render a real label without
 * loading every channel up front.
 */
const canvasInfo = new Map<string, { name: string; templateId: string }>();
const taskInfo = new Map<string, string>();

/** Bounded insert (most-recent kept) so the caches don't grow unbounded over a
 * long session. */
const MAX_CACHE_ENTRIES = 200;
function remember<V>(map: Map<string, V>, key: string, value: V): void {
  map.delete(key);
  map.set(key, value);
  if (map.size > MAX_CACHE_ENTRIES) {
    const oldest = map.keys().next().value;
    if (oldest !== undefined) map.delete(oldest);
  }
}

// True when the open task's focused editor panel has a closeable active tab.
// Cmd+W is inner-first: it closes that editor tab (handled by
// usePanelKeyboardShortcuts) before it closes the browser tab.
function taskHasCloseableEditorTab(taskId: string | undefined): boolean {
  if (!taskId) return false;
  const layout = usePanelLayoutStore.getState().getLayout(taskId);
  const panelId = layout?.focusedPanelId;
  if (!panelId || !layout?.panelTree) return false;
  const panel = getLeafPanel(layout.panelTree, panelId);
  const activeTab = panel?.content.tabs.find(
    (t) => t.id === panel.content.activeTabId,
  );
  return !!activeTab && activeTab.closeable !== false;
}

type TabRef = {
  id: string;
  dashboardId: string | null;
  taskId: string | null;
  channelId: string | null;
  channelSection: string | null;
  appView: string | null;
};

// The top-level app pages that can be a tab. Keyed by useAppView's view.type;
// each maps to its canonical route (a task/canvas/channel tab has its own
// route, these don't) plus the strip's label + icon.
type AppView = "inbox" | "agents" | "skills" | "mcp-servers" | "command-center";

const APP_VIEW_META: Record<AppView, { label: string; icon: ReactNode }> = {
  inbox: { label: "Inbox", icon: <TrayIcon size={14} /> },
  agents: { label: "Agents", icon: <RobotIcon size={14} /> },
  skills: { label: "Skills", icon: <BrainIcon size={14} /> },
  "mcp-servers": {
    label: "MCP servers",
    icon: <PlugsConnectedIcon size={14} />,
  },
  "command-center": {
    label: "Command center",
    icon: <SquaresFourIcon size={14} />,
  },
};

function isAppView(value: string): value is AppView {
  return value in APP_VIEW_META;
}

export function BrowserTabStrip() {
  const logger = useService<RootLogger>(ROOT_LOGGER);
  const snapshot = useTabsSnapshot();
  const navigate = useNavigate();
  const router = useRouter();
  const trpc = useHostTRPC();
  const params = useParams({ strict: false }) as {
    channelId?: string;
    dashboardId?: string;
    taskId?: string;
  };
  const historyTabId = useRouterState({
    select: (s) => s.location.state.tabId,
  });
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // Tabs work in both spaces: channel-scoped tabs live under /website, while a
  // plain task tab (no channel) belongs to the Code experience. The space
  // decides where a task/blank tab navigates.
  const inChannels = pathname.startsWith("/website");
  // Top-level app pages (Inbox, Agents, Skills, MCP servers, Command Center)
  // are tab targets too. useAppView normalizes both the /code routes and
  // their /website mirrors to the same view.type, so a tab survives either space.
  const view = useAppView();
  const routeAppView: AppView | null = isAppView(view.type) ? view.type : null;

  const { channels } = useChannels();
  const { createChannel } = useChannelMutations();
  // Whether the channels surface is live — the same gate the sidebar uses. This
  // (not the current route) decides a new tab's default: with channels on a
  // fresh tab opens #me, otherwise the Code new-task screen. Keying off the
  // route would leave the behaviour stale right after the toggle flips.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsEnabled =
    useSidebarStore((s) => s.channelsEnabled) && bluebirdEnabled;

  // A cloud run is read-only, so opening a new tab there makes no sense — hide
  // the new-tab button and disable its Cmd/Ctrl+T shortcut. Off a task route
  // params.taskId is undefined, so this is false and the button stays.
  const isCloudRun = useIsWorkspaceCloudRun(params.taskId);

  // The active channel sub-section (artifacts/history/context) is the
  // route segment after the channelId. Null when on the channel home or a
  // non-section route (canvas/task), so a channel-home tab labels by name.
  const routeChannelSection = useMemo(() => {
    if (!params.channelId) return null;
    const seg = pathname.split("/")[3] ?? null;
    return channelSectionFor(seg)?.key ?? null;
  }, [pathname, params.channelId]);

  // Local-first sync (see tabsSync.ts): every operation applies its shared
  // pure transform to the mirror synchronously via applyLocalTransform, then
  // persists in the background via persistWrite. The mutations below are pure
  // transport — their returned snapshots are handled by persistWrite's
  // last-settle reconcile, never applied directly, so a stale echo can't
  // rewind the mirror mid-interaction.
  const openOrFocus = useMutation(
    trpc.browserTabs.openOrFocus.mutationOptions(),
  );
  const newBlankTab = useMutation(
    trpc.browserTabs.newBlankTab.mutationOptions(),
  );
  const setTabTarget = useMutation(
    trpc.browserTabs.setTabTarget.mutationOptions(),
  );
  const close = useMutation(trpc.browserTabs.close.mutationOptions());
  const closeMany = useMutation(trpc.browserTabs.closeMany.mutationOptions());
  const setOrder = useMutation(trpc.browserTabs.setOrder.mutationOptions());
  const setActiveTab = useMutation(
    trpc.browserTabs.setActiveTab.mutationOptions(),
  );

  const pinnedTabIds = usePinnedTabsStore((s) => s.pinnedTabIds);
  const togglePinned = usePinnedTabsStore((s) => s.togglePinned);
  const prunePinned = usePinnedTabsStore((s) => s.prune);
  // Transient reorder preview (set while a pill is dragged); overrides the
  // strip's order without touching the domain snapshot mirror.
  const previewOrder = useTabReorderStore((s) => s.previewOrder);
  // Drop pins for tabs that no longer exist (closed here or in another
  // window). Skip the pre-seed empty snapshot so a slow boot doesn't wipe pins.
  useEffect(() => {
    if (snapshot.windows.length === 0) return;
    prunePinned(snapshot.tabs.map((t) => t.id));
  }, [snapshot, prunePinned]);

  const win = primaryWindow(snapshot);
  const windowId = win?.id;
  // The history state flips the instant you navigate, while the server snapshot
  // round-trips — so prefer it for "which tab is active" to avoid a one-step lag
  // in the highlight and the name. Validate it against the live tab list first:
  // back/forward can replay an entry tagged with a since-closed tab, and a dead
  // id here would blank the strip highlight and point Cmd+W at a tab that no
  // longer exists (the navigation effect heals the tag, but asynchronously).
  const historyTabIsLive =
    !!historyTabId && snapshot.tabs.some((t) => t.id === historyTabId);
  const activeTabId =
    (historyTabIsLive ? historyTabId : null) ?? win?.activeTabId ?? null;

  // Names feed the tab labels. The channel canvas list + all-tasks list cover
  // most tabs; a direct fetch of the *current route's* canvas/task (warm cache
  // from the detail page) makes the focused tab's name update the instant you
  // navigate — keyed off the route, not the tab's stored (lagging) target.
  // Only poll the all-tasks list when a task tab actually needs a title.
  const hasTaskTab = snapshot.tabs.some((t) => t.taskId != null);
  const { dashboards } = useDashboards(params.channelId);
  const { dashboard: activeRecord } = useDashboard(params.dashboardId);
  const { data: allTasks } = useTasks(undefined, { enabled: hasTaskTab });
  const { data: activeTaskRecord } = useQuery({
    ...taskDetailQuery(params.taskId ?? ""),
    enabled: !!params.taskId,
  });
  // Remember names so a background tab from another channel keeps its label
  // after its channel's list unloads. Written in an effect (not during render)
  // to keep render pure; the tabs memo reads the live lists first anyway.
  useEffect(() => {
    for (const d of dashboards) {
      remember(canvasInfo, d.id, { name: d.name, templateId: d.templateId });
    }
    if (activeRecord) {
      remember(canvasInfo, activeRecord.id, {
        name: activeRecord.name,
        templateId: activeRecord.templateId,
      });
    }
    for (const t of allTasks ?? []) remember(taskInfo, t.id, t.title);
    if (activeTaskRecord) {
      remember(taskInfo, activeTaskRecord.id, activeTaskRecord.title);
    }
  }, [dashboards, activeRecord, allTasks, activeTaskRecord]);

  // Resolve what the current location means for the strip (see
  // decideTabNavigation) and apply it: focus a tab, replace the active tab's
  // target in place, open a tab, and/or stamp the history entry with the tab it
  // belongs to so back/forward can replay it.
  //
  // Keyed on the LOCATION only — the route is the command stream; the mirror is
  // state this effect reconciles against, read fresh via readMirror() rather
  // than subscribed to. Running on mirror changes is actively wrong under
  // local-first sync: a handler moves the mirror BEFORE it navigates (e.g. the
  // + tab appends and focuses a blank tab), and an effect run in that gap sees
  // the OLD location's tag disagree with the new mirror focus and "activates"
  // the stale tab — yanking focus back and mis-targeting the follow-up
  // navigation as an in-tab replace of the wrong tab.
  useEffect(() => {
    if (!windowId) return;
    const stamp = (tabId: string) => {
      const loc = router.history.location;
      // Already tagged — skip the replace so history entries and router
      // subscribers don't churn.
      if ((loc.state as { tabId?: string }).tabId === tabId) return;
      // Use the full href (always a string); reconstructing from pathname +
      // search crashes because search is parsed to an object at runtime.
      router.history.replace(loc.href, { ...(loc.state as object), tabId });
    };
    const mirror = readMirror();
    const mirrorWin = primaryWindow(mirror);
    const mirrorTabs = mirror.tabs.filter((t) => t.windowId === windowId);
    const mirrorActive = mirrorWin?.activeTabId
      ? mirrorTabs.find((t) => t.id === mirrorWin.activeTabId)
      : undefined;
    const decision = decideTabNavigation({
      historyTabId: historyTabId ?? null,
      // Validates history tags: back/forward can replay an entry tagged with a
      // closed tab; activating that dead id would persist a dangling
      // activeTabId, after which every nav "opens" (no active tab found).
      windowTabIds: mirrorTabs.map((t) => t.id),
      // Identities of this window's tabs, so a navigation to a target already
      // open in another tab focuses it instead of duplicating it (and a rapid
      // switch whose history stamp was lost self-heals to the right tab).
      windowTabs: mirrorTabs.map((t) => ({
        id: t.id,
        dashboardId: t.dashboardId,
        taskId: t.taskId,
        channelId: t.channelId,
        channelSection: t.channelSection,
        appView: t.appView,
      })),
      serverActiveTabId: mirrorWin?.activeTabId ?? null,
      activeTab: mirrorActive
        ? {
            id: mirrorActive.id,
            dashboardId: mirrorActive.dashboardId,
            taskId: mirrorActive.taskId,
            channelId: mirrorActive.channelId,
            channelSection: mirrorActive.channelSection,
            appView: mirrorActive.appView,
          }
        : null,
      routeDashboardId: params.dashboardId ?? null,
      routeTaskId: params.taskId ?? null,
      routeChannelId: params.channelId ?? null,
      routeChannelSection,
      routeAppView,
    });
    switch (decision.type) {
      case "activate": {
        // Focus in the mirror synchronously; persist in the background.
        applyLocalTransform((s) =>
          setWindowActiveTab(s, windowId, decision.tabId),
        );
        void persistWrite(() =>
          setActiveTab.mutateAsync({ windowId, tabId: decision.tabId }),
        );
        // Heal the history tag to the tab we're activating. Normally it already
        // matches (a tagged switch), so `stamp` no-ops. When the dedup path
        // activated an existing tab the route pointed at (a switch whose stamp
        // was lost), the entry still carries the STALE tab — left unhealed, the
        // first branch above would re-activate it next render and ping-pong with
        // the dedup (a "Maximum update depth exceeded" loop). Stamping breaks it.
        stamp(decision.tabId);
        break;
      }
      case "replace": {
        const target = {
          tabId: decision.tabId,
          dashboardId: decision.dashboardId,
          taskId: decision.taskId,
          channelId: decision.channelId,
          channelSection: decision.channelSection,
          appView: decision.appView,
        };
        // Synchronous local apply keeps re-entrant runs (and the /website index
        // redirect guard) from ever seeing the pre-navigation target.
        applyLocalTransform((s) =>
          setTabTargetLocal(s, { ...target, now: Date.now }),
        );
        void persistWrite(() => setTabTarget.mutateAsync(target));
        if (decision.stampTabId) stamp(decision.stampTabId);
        break;
      }
      case "open": {
        const input = {
          windowId,
          dashboardId: decision.dashboardId,
          taskId: decision.taskId,
          channelId: decision.channelId,
          channelSection: decision.channelSection,
          appView: decision.appView,
        };
        // Mint the id here so the local apply and the persisted state agree on
        // it; openOrFocusLocal may instead dedup-focus an existing tab, in
        // which case the minted id goes unused (identically on the server).
        const mintedId = crypto.randomUUID();
        let openedTabId: string = mintedId;
        applyLocalTransform((s) => {
          const result = openOrFocusLocal(s, {
            ...input,
            makeId: () => mintedId,
            now: Date.now,
          });
          openedTabId = result.tabId;
          return result.snapshot;
        });
        void persistWrite(() =>
          openOrFocus.mutateAsync({ ...input, tabId: mintedId }),
        );
        // Stamp the entry with the tab that now owns this route.
        stamp(openedTabId);
        break;
      }
      case "stamp":
        stamp(decision.stampTabId);
        break;
    }
  }, [
    // windowId flips once when the boot seed lands — that run adopts the
    // initial route. Everything else here is location; mirror state is read
    // fresh inside, deliberately NOT a dependency (see the comment above).
    windowId,
    historyTabId,
    params.channelId,
    params.dashboardId,
    params.taskId,
    routeChannelSection,
    routeAppView,
    openOrFocus.mutateAsync,
    setTabTarget.mutateAsync,
    setActiveTab.mutateAsync,
    router,
  ]);

  const channelName = useMemo(() => {
    const map = new Map(channels.map((c) => [c.id, c.name]));
    return (id: string | null) => (id ? (map.get(id) ?? null) : null);
  }, [channels]);

  const tabs: TabView[] = useMemo(() => {
    if (!windowId) return [];
    // Reference the reactive sources directly so labels recompute the instant a
    // name resolves — not just when the snapshot changes.
    const resolveCanvas = (id: string) => {
      if (activeRecord?.id === id) {
        return { name: activeRecord.name, templateId: activeRecord.templateId };
      }
      const fromList = dashboards.find((d) => d.id === id);
      if (fromList) {
        return { name: fromList.name, templateId: fromList.templateId };
      }
      return canvasInfo.get(id);
    };
    const findTask = (id: string) =>
      activeTaskRecord?.id === id
        ? activeTaskRecord
        : allTasks?.find((t) => t.id === id);

    const pinnedSet = new Set(pinnedTabIds);
    const byId = new Map(snapshot.tabs.map((t) => [t.id, t]));
    // Base stored order — during a drag, the transient preview order overrides
    // it (filtered to live tabs; any tab not in the preview is appended in
    // stored order). The pinned-first partition is applied on top.
    const stored = storedOrderIds(snapshot, windowId);
    let base = stored;
    if (previewOrder) {
      const live = new Set(stored);
      const seen = new Set(previewOrder);
      base = [
        ...previewOrder.filter((id) => live.has(id)),
        ...stored.filter((id) => !seen.has(id)),
      ];
    }
    return partitionPinnedFirst(base, pinnedTabIds)
      .map((id) => byId.get(id))
      .filter((t) => t !== undefined)
      .map((t): TabView => {
        const pinned = pinnedSet.has(t.id);
        // The active tab shows the current route's target, so resolve from the
        // route (instant) rather than its stored ids (which lag a navigation).
        const isActive = t.id === activeTabId;
        const taskId = isActive ? (params.taskId ?? null) : t.taskId;
        const dashId = isActive ? (params.dashboardId ?? null) : t.dashboardId;
        const channelId = isActive ? (params.channelId ?? null) : t.channelId;
        const section = isActive ? routeChannelSection : t.channelSection;
        const appView = isActive ? routeAppView : t.appView;
        const channel = channelName(channelId);
        if (taskId) {
          const task = findTask(taskId);
          return {
            id: t.id,
            label: task?.title ?? taskInfo.get(taskId) ?? "Task",
            icon: <TaskTabIcon task={task} size={14} />,
            channelName: channel,
            pinned,
          };
        }
        if (dashId) {
          const info = resolveCanvas(dashId);
          return {
            id: t.id,
            label: info?.name ?? "Canvas",
            icon: iconForTemplate(info?.templateId ?? "freeform", {
              size: 14,
            }),
            channelName: channel,
            pinned,
          };
        }
        // A channel tab: a sub-section (Artifacts/Recents/…) or the channel home.
        // The section drives the label; the channel name carries the `#` hover
        // context. Home has no section, so it labels by the channel name.
        if (channelId) {
          const meta = channelSectionFor(section);
          return {
            id: t.id,
            label: meta?.label ?? channel ?? "Channel",
            icon: <HashIcon size={14} />,
            channelName: channel,
            // No section meta → the channel's index page.
            isChannelHome: !meta,
            pinned,
          };
        }
        // A top-level app page (Inbox, Agents, Skills, …).
        if (appView && isAppView(appView)) {
          return {
            id: t.id,
            label: APP_VIEW_META[appView].label,
            icon: APP_VIEW_META[appView].icon,
            channelName: null,
            pinned,
          };
        }
        return { id: t.id, label: "New tab", channelName: null, pinned };
      });
  }, [
    snapshot,
    windowId,
    pinnedTabIds,
    previewOrder,
    channelName,
    dashboards,
    activeRecord,
    allTasks,
    activeTaskRecord,
    activeTabId,
    params.channelId,
    params.dashboardId,
    params.taskId,
    routeChannelSection,
    routeAppView,
  ]);

  // Navigate to a tab, tagging the history entry with its id so the switch is
  // replayable by back/forward. A canvas/task tab goes to its route; a blank tab
  // pushes a plain entry (the empty placeholder renders from the active tab).
  const goToTab = (tab: TabRef) => {
    const state = (prev: object) => ({ ...prev, tabId: tab.id });
    if (tab.taskId && tab.channelId) {
      navigate({
        to: "/website/$channelId/tasks/$taskId",
        params: { channelId: tab.channelId, taskId: tab.taskId },
        state,
      });
    } else if (tab.taskId) {
      // A channel-less task tab — the Code task detail route.
      navigate({
        to: "/code/tasks/$taskId",
        params: { taskId: tab.taskId },
        state,
      });
    } else if (tab.dashboardId && tab.channelId) {
      navigate({
        to: "/website/$channelId/dashboards/$dashboardId",
        params: { channelId: tab.channelId, dashboardId: tab.dashboardId },
        state,
      });
    } else if (tab.channelId) {
      const params = { channelId: tab.channelId };
      // Section keys are the route segments; unknown/stale sections (e.g. from
      // a since-removed tab type) fall back to the channel home.
      const section = channelSectionFor(tab.channelSection);
      if (section) {
        navigate({
          to: `/website/$channelId/${section.key}` as const,
          params,
          state,
        });
      } else {
        navigate({ to: "/website/$channelId", params, state });
      }
    } else if (tab.appView && isAppView(tab.appView)) {
      // A top-level app page — back to its canonical route (literal `to` per
      // case so the router types stay checked).
      switch (tab.appView) {
        case "inbox":
          navigate({ to: "/code/inbox", state });
          break;
        case "agents":
          navigate({ to: "/code/agents", state });
          break;
        case "skills":
          navigate({ to: "/skills", state });
          break;
        case "mcp-servers":
          navigate({ to: "/mcp-servers", state });
          break;
        case "command-center":
          navigate({ to: "/command-center", state });
          break;
        default: {
          // Exhaustiveness guard: a new AppView value fails to compile here
          // until its canonical route is wired above — so the tab-target set
          // (union + APP_VIEW_META) and this navigation can't drift apart.
          const _exhaustive: never = tab.appView;
          return _exhaustive;
        }
      }
    } else {
      // Blank / landing tab: park on the space's home — the channels index, or
      // the Code new-task screen.
      navigate({ to: inChannels ? "/website" : "/code", state });
    }
  };

  const handleSelect = (tabId: string) => {
    const tab = snapshot.tabs.find((t) => t.id === tabId);
    if (!tab || !windowId) return;
    // goToTab stamps historyTabId; the navigation effect picks it up and issues
    // setActiveTab via the "activate" path — no need to also fire it here.
    goToTab(tab);
  };

  // Navigate to the close's survivor, or — when the last tab was closed — to the
  // flag's default landing (#me / new-task), never the /website index (which
  // would redirect to channels[0], re-opening a random channel tab).
  const applyCloseResult = (next: TabsSnapshot) => {
    const w = primaryWindow(next);
    const active = w?.activeTabId
      ? next.tabs.find((t) => t.id === w.activeTabId)
      : null;
    if (active) goToTab(active);
    else landOnDefault();
  };

  // Close applies locally and navigates to the survivor in the same tick — the
  // /website index therefore always renders against the post-close snapshot
  // and can't redirect (re-opening a tab) mid-flight.
  const handleClose = (tabId: string) => {
    const next = applyLocalTransform((s) => closeTabLocal(s, tabId).snapshot);
    applyCloseResult(next);
    void persistWrite(() => close.mutateAsync({ tabId }));
  };

  // Unpinning re-homes the tab at the front of the unpinned block. Apply the
  // reorder optimistically (in the same tick as the pin toggle) so the tab
  // doesn't visibly jump from its stored slot to the front a round-trip later.
  const handleTogglePin = (tabId: string) => {
    const wasPinned = pinnedTabIds.includes(tabId);
    togglePinned(tabId);
    if (!wasPinned || !windowId) return;
    const order = frontOfUnpinnedOrder(snapshot, windowId, tabId, pinnedTabIds);
    applyLocalTransform((s) => setTabOrder(s, windowId, order));
    void persistWrite(() => setOrder.mutateAsync({ windowId, tabIds: order }));
  };

  // Bulk closes operate on the strip's *displayed* order (pinned-first) and
  // never take pinned tabs with them. The anchor (the right-clicked tab, which
  // always survives) takes focus if the active tab was among those closed.
  const handleCloseMany = (tabIds: string[], anchorTabId: string) => {
    if (tabIds.length === 0) return;
    const next = applyLocalTransform((s) =>
      closeTabsLocal(s, tabIds, anchorTabId),
    );
    applyCloseResult(next);
    void persistWrite(() =>
      closeMany.mutateAsync({ tabIds, focusTabId: anchorTabId }),
    );
  };

  const handleCloseOthers = (tabId: string) => {
    handleCloseMany(
      tabs.filter((t) => t.id !== tabId && !t.pinned).map((t) => t.id),
      tabId,
    );
  };

  const handleCloseToRight = (tabId: string) => {
    const idx = tabs.findIndex((t) => t.id === tabId);
    if (idx === -1) return;
    handleCloseMany(
      tabs
        .slice(idx + 1)
        .filter((t) => !t.pinned)
        .map((t) => t.id),
      tabId,
    );
  };

  const handleCloseToLeft = (tabId: string) => {
    const idx = tabs.findIndex((t) => t.id === tabId);
    if (idx === -1) return;
    handleCloseMany(
      tabs
        .slice(0, idx)
        .filter((t) => !t.pinned)
        .map((t) => t.id),
      tabId,
    );
  };

  // The default landing, keyed off the channels toggle (not the current route,
  // which lags a toggle flip): #me when channels are on, the Code new-task
  // screen otherwise. Deliberately never routes through the /website index,
  // which would redirect to channels[0]. `tabId` (a fresh blank tab) fills that
  // tab in place; without one (last tab closed) the navigation opens a new tab.
  const landOnDefault = (tabId?: string) => {
    const state = tabId ? (prev: object) => ({ ...prev, tabId }) : undefined;
    if (!channelsEnabled) {
      navigate({ to: "/code", state });
      return;
    }
    // #me is provisioned lazily the first time (same bridge the sidebar's #me
    // row uses); fall back to the new-task screen if it can't be created.
    void (async () => {
      try {
        const folder = await ensurePersonalChannel(channels, createChannel);
        navigate({
          to: "/website/$channelId",
          params: { channelId: folder.id },
          state,
        });
      } catch {
        navigate({ to: "/code", state });
      }
    })();
  };

  // New tab is fully local: mint the id here, append the blank tab to the
  // mirror and navigate in the same tick (no IPC wait), then persist with the
  // same id so the durable state matches. The service is idempotent on the
  // minted id, so a replay can't append a duplicate.
  const createBlankTab = (targetWindowId: string) => {
    const tabId = crypto.randomUUID();
    applyLocalTransform(
      (s) =>
        newBlankTabLocal(s, {
          windowId: targetWindowId,
          makeId: () => tabId,
          now: Date.now,
        }).snapshot,
    );
    landOnDefault(tabId);
    void persistWrite(() =>
      newBlankTab.mutateAsync({ windowId: targetWindowId, tabId }),
    );
  };

  const handleNewTab = () => {
    if (windowId) {
      createBlankTab(windowId);
      return;
    }
    // No window means the mirror never seeded (the boot fetch raced or
    // failed) — the click must not die. Re-pull the authoritative snapshot
    // (the server always has a primary window) and append into it. Resolve
    // the window from the FETCHED snapshot, not the mirror: reseedMirror
    // skips the store apply when a local write or newer remote push raced
    // the fetch, and the mirror could still be windowless then.
    void reseedMirror()
      .then((server) => {
        const win = server
          ? primaryWindow(server)
          : primaryWindow(readMirror());
        if (win) {
          createBlankTab(win.id);
          return;
        }
        // Should be unreachable (the server always mints a primary window),
        // but a silent skip here reproduces the dead-"+" this path exists to
        // fix — make it loud instead.
        logger.error("browser-tabs: new-tab found no window after reseed");
      })
      .catch((error) => {
        logger.error("browser-tabs: new-tab reseed failed", { error });
      });
  };

  // Cmd/Ctrl+T opens a new browser tab. Bound here (not globally) so it only
  // fires where the strip is mounted; the new-task shortcut owns Cmd/Ctrl+N.
  useHotkeys(
    SHORTCUTS.NEW_TAB,
    (e) => {
      e.preventDefault();
      handleNewTab();
    },
    {
      enableOnFormTags: true,
      enableOnContentEditable: true,
      enabled: !isCloudRun,
    },
  );

  // Cmd/Ctrl+W closes the active browser tab. Always preventDefault so Electron
  // doesn't close the window, but defer to the task's editor panel when it has a
  // closeable tab (inner-first) — that handler closes the editor tab instead.
  useHotkeys(
    SHORTCUTS.CLOSE_TAB,
    (e) => {
      e.preventDefault();
      if (taskHasCloseableEditorTab(params.taskId)) return;
      if (activeTabId) handleClose(activeTabId);
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
  );

  // With channels on, Cmd/Ctrl+1-9 switches to the Nth browser tab (in the
  // displayed, pinned-first order) instead of the Nth sidebar task. The global
  // task-switch handler yields via the same channelsEnabled gate, so exactly one
  // owner fires. Mirror its pure-ctrl guard: ctrl+1-9 is the editor-panel tab
  // switcher (SWITCH_TAB), so leave ctrl-only presses to it.
  useHotkeys(
    SHORTCUTS.SWITCH_TASK,
    (event, handler) => {
      if (event.ctrlKey && !event.metaKey) return;
      const key = handler.keys?.[0];
      if (!key) return;
      const tab = tabs[Number.parseInt(key, 10) - 1];
      if (tab) handleSelect(tab.id);
    },
    {
      enableOnFormTags: true,
      enableOnContentEditable: true,
      preventDefault: true,
      enabled: channelsEnabled,
    },
    [tabs, handleSelect],
  );

  return (
    <TabStrip
      tabs={tabs}
      activeTabId={activeTabId}
      onSelect={handleSelect}
      onClose={handleClose}
      onTogglePin={handleTogglePin}
      onCloseOthers={handleCloseOthers}
      onCloseToRight={handleCloseToRight}
      onCloseToLeft={handleCloseToLeft}
      onNewTab={isCloudRun ? undefined : handleNewTab}
    />
  );
}
