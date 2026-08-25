import { useService } from "@posthog/di/react";
import {
  closeTab as closeTabLocal,
  closeTabs as closeTabsLocal,
  decideTabNavigation,
  openTab as openTabLocal,
  primaryWindow,
  setTabOrder,
  setTabTarget as setTabTargetLocal,
  setWindowActiveTab,
  type TabIdentity,
  type TabsSnapshot,
  type TabViewState,
} from "@posthog/shared";
import { channelSectionFor } from "@posthog/ui/features/canvas/channelSections";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  useDashboard,
  useDashboards,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useRailPane } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import {
  applyTabViewState,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { useActiveSession } from "@posthog/ui/features/navigation/useActiveSession";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { getLeafPanel } from "@posthog/ui/features/panels/panelStoreHelpers";
import { getTaskInputSessionId } from "@posthog/ui/features/task-detail/taskInputSession";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useAppView } from "@posthog/ui/router/useAppView";
import { isMac } from "@posthog/ui/utils/platform";
import { useQuery } from "@tanstack/react-query";
import {
  useNavigate,
  useParams,
  useRouter,
  useRouterState,
} from "@tanstack/react-router";
import { useCallback, useEffect, useMemo } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { shouldHandleBrowserTabSwitch } from "./browserTabShortcuts";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "./browserTabsClient";
import {
  frontOfUnpinnedOrder,
  partitionPinnedFirst,
  storedOrderIds,
} from "./displayOrder";
import { usePinnedTabsStore } from "./pinnedTabsStore";
import { settledLocation } from "./settledLocation";
import { TabStrip, type TabView } from "./TabStrip";
import { TaskTabDot } from "./TaskTabMarks";
import {
  isTabAppView,
  TAB_APP_VIEW_META,
  type TabAppView,
} from "./tabAppViews";
import { pushTabHistoryEntry } from "./tabHistory";
import { useTabReorderStore } from "./tabReorderStore";
import { applyLocalTransform, persistWrite, readMirror } from "./tabsSync";
import { useTabsSnapshot } from "./useBrowserTabs";
import { useOpenBrowserTab } from "./useOpenBrowserTab";

/**
 * Module-level caches of display info, keyed by id. Tabs store only references;
 * names are resolved here as the user navigates (which loads each channel's
 * canvases/tasks), so cross-channel tabs still render a real label without
 * loading every channel up front.
 */
const canvasInfo = new Map<string, { name: string; templateId: string }>();
const taskInfo = new Map<string, string>();
const BLANK_TAB_HREF = "/activity";

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
  /** Where the tab is. Null only for tabs persisted before hrefs were stored. */
  href: string | null;
  dashboardId: string | null;
  taskId: string | null;
  channelId: string | null;
  channelSection: string | null;
  appView: string | null;
};

export function BrowserTabStrip() {
  const spacesLayout = useChannelsLayout();
  const snapshot = useTabsSnapshot();
  const navigate = useNavigate();
  const router = useRouter();
  const client = useService<BrowserTabsClient>(BROWSER_TABS_CLIENT);
  const openBrowserTab = useOpenBrowserTab();
  const params = useParams({ strict: false }) as {
    channelId?: string;
    dashboardId?: string;
    taskId?: string;
  };
  // The in-flight tag: flips the instant you navigate, so the strip's highlight
  // and the active tab's name don't lag a navigation behind. Rendering only —
  // the effect below must not write from it (see settledLocation).
  const historyTabId = useRouterState({
    select: (s) => s.location.state.tabId,
  });
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // What the effect reconciles against: the settled href and the tab that entry
  // belongs to, read from one snapshot (see settledLocation for why that
  // matters). `href`, not pathname — search params are part of where a tab is,
  // and reconstructing `pathname + search` crashes because search is parsed to
  // an object at runtime.
  const settled = useRouterState({ select: settledLocation });
  const locationHref = settled.href;
  const settledTabId = settled.tabId;
  const locationIsCurrent = settled.isCurrent;
  // The nav state the href cannot express: which sidebar pane is drawn, and the
  // space it is drawn over. Recorded per tab so two tabs can sit on different
  // spaces with different sidebars.
  const listOpen = useChannelPaneStore((s) => s.pane === "list");
  const scopedSpaceId = useCurrentChannelStore((s) => s.currentChannelId);
  // Which rail destination this location belongs to, so the tab can remember
  // where that destination was when it left.
  const railPane = useRailPane();
  // Which session the content pane is about, wherever it came from: a path
  // param, Activity's picked item, or a feed's.
  const activeSession = useActiveSession();
  // Top-level app pages are tab targets too. Their typed metadata keeps route
  // classification, persisted labels, and rendered labels in one vocabulary.
  const view = useAppView();
  const routeAppView: TabAppView | null = isTabAppView(view.type)
    ? view.type
    : null;

  const { channels } = useChannels();
  // With channel reports on, a restored inbox tab lands on the spaces index
  // (the inbox is gone as a destination).
  const channelReportsEnabled = useChannelReportsEnabled();

  // The active channel sub-section (artifacts/history/context) is the
  // route segment after the channelId. Null when on the channel home or a
  // non-section route (canvas/task), so a channel-home tab labels by name.
  const routeChannelSection = useMemo(() => {
    if (!params.channelId) return null;
    const seg = pathname.split("/")[3] ?? null;
    return channelSectionFor(seg)?.key ?? null;
  }, [pathname, params.channelId]);

  // Local-first sync (see tabsSync.ts): each mutation applies its shared pure
  // transform to the mirror synchronously via applyLocalTransform, then
  // persists in the background via persistWrite. Selection itself is
  // history-first; the settled navigation triggers its local focus mutation.
  // The mutations below are pure transport — their returned snapshots are
  // handled by persistWrite's last-settle reconcile, never applied directly,
  // so a stale echo can't rewind the mirror mid-interaction.
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

  const channelName = useMemo(() => {
    const map = new Map(channels.map((c) => [c.id, c.name]));
    return (id: string | null) => (id ? (map.get(id) ?? null) : null);
  }, [channels]);

  // Names feed the tab labels. The channel canvas list + all-tasks list cover
  // most tabs; a direct fetch of the *current route's* canvas/task (warm cache
  // from the detail page) makes the focused tab's name update the instant you
  // navigate — keyed off the route, not the tab's stored (lagging) target.
  // Only poll the all-tasks list when a task tab actually needs a title.
  const hasTaskTab = snapshot.tabs.some((t) => t.taskId != null);
  const { dashboards } = useDashboards(params.channelId);
  const { dashboard: activeRecord } = useDashboard(params.dashboardId);
  const { data: allTasks } = useTasks(undefined, { enabled: hasTaskTab });
  // Keyed on the active SESSION, not the path param: on Activity the session
  // comes from the route's search, and without this its title would wait on the
  // all-tasks list (itself gated on a tab already carrying a taskId).
  const { data: activeTaskRecord } = useQuery({
    ...taskDetailQuery(activeSession.taskId ?? ""),
    enabled: !!activeSession.taskId,
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

  // The name the active tab resolves for itself, stored so the tab still reads
  // as a session (not as its space) while it is in the background. Null while
  // the record is still loading, which keeps a loading frame from overwriting
  // the name already stored.
  const activeTitle = useMemo(() => {
    const sessionId = activeSession.taskId;
    if (sessionId) {
      if (activeTaskRecord?.id === sessionId) return activeTaskRecord.title;
      return allTasks?.find((t) => t.id === sessionId)?.title ?? null;
    }
    if (params.dashboardId) {
      if (activeRecord?.id === params.dashboardId) return activeRecord.name;
      return dashboards.find((d) => d.id === params.dashboardId)?.name ?? null;
    }
    return null;
  }, [
    activeSession.taskId,
    params.dashboardId,
    activeTaskRecord,
    allTasks,
    activeRecord,
    dashboards,
  ]);

  const routeTitle = useMemo(() => {
    if (activeTitle) return activeTitle;
    const currentChannelId =
      params.channelId ?? activeSession.channelId ?? null;
    if (currentChannelId) {
      const channel = channelName(currentChannelId);
      return channelSectionFor(routeChannelSection)?.label ?? channel;
    }
    if (routeAppView) return TAB_APP_VIEW_META[routeAppView].label;
    return null;
  }, [
    activeTitle,
    params.channelId,
    activeSession.channelId,
    channelName,
    routeChannelSection,
    routeAppView,
  ]);

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
    // A history push updates `location` before `resolvedLocation`. Writing in
    // that gap can restamp the new entry with the outgoing tab, so the route
    // must fully own both its href and tab tag before reconciliation starts.
    if (!windowId || !locationIsCurrent) return;
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
    // The label/icon cache written alongside the location. Never the thing the
    // decision is made on: it is all-null outside its vocabulary, so two
    // unrelated routes look identical through it.
    const identity: TabIdentity = {
      dashboardId: params.dashboardId ?? null,
      // `activeSession`, not `params`: Activity and a feed read a session into
      // the pane from their route's SEARCH rather than a path param, so the tab
      // would otherwise show "New tab" over an open session.
      taskId: activeSession.taskId ?? null,
      channelId: params.channelId ?? activeSession.channelId ?? null,
      channelSection: routeChannelSection,
      appView: routeAppView,
    };
    // Where each rail destination was when this tab last left it, carried
    // forward from the tab's own memory. Per tab, so one tab's rail click can
    // never restore an href another tab established. One writer: this effect
    // runs on every settled navigation, including the ones a rail click does
    // not make (hotkeys, deep links, links in the content).
    const visit = {
      href: locationHref,
      ...(railPane === "spaces" ? { listOpen, spaceId: scopedSpaceId } : {}),
    };
    const viewState: TabViewState = {
      // Keep the stored name when nothing has resolved yet, so a loading frame
      // does not blank a background tab's label.
      title: routeTitle ?? mirrorActive?.viewState?.title,
      listOpen,
      spaceId: scopedSpaceId,
      lastByPane: {
        ...(mirrorActive?.viewState?.lastByPane ?? {}),
        [railPane]: visit,
      },
    };
    const decision = decideTabNavigation({
      // The SETTLED tag, not the in-flight one. Pairing the in-flight tag with
      // the settled href tells the effect "tab B is on tab A's href", and it
      // dutifully writes A's href onto B.
      historyTabId: settledTabId,
      // Validates history tags: back/forward can replay an entry tagged with a
      // closed tab; activating that dead id would persist a dangling
      // activeTabId, after which every nav "opens" (no active tab found).
      windowTabIds: mirrorTabs.map((t) => t.id),
      serverActiveTabId: mirrorWin?.activeTabId ?? null,
      activeTab: mirrorActive
        ? {
            id: mirrorActive.id,
            href: mirrorActive.href,
            viewState: mirrorActive.viewState ?? null,
            identity: {
              dashboardId: mirrorActive.dashboardId,
              taskId: mirrorActive.taskId,
              channelId: mirrorActive.channelId,
              channelSection: mirrorActive.channelSection,
              appView: mirrorActive.appView,
            },
          }
        : null,
      href: locationHref,
      viewState,
      identity,
    });
    const location = { href: locationHref, viewState };
    switch (decision.type) {
      case "activate": {
        // Put this tab's sidebar back before anything else runs. The pane and
        // the scoped space are window-global, so without this the next pass
        // reads the tab we LEFT and replaces this tab's stored view state with
        // it — switching to a tab would erase its own memory.
        const target = mirrorTabs.find((t) => t.id === decision.tabId);
        if (target?.viewState) applyTabViewState(target.viewState);
        // Focus in the mirror synchronously; persist in the background.
        applyLocalTransform((s) =>
          setWindowActiveTab(s, windowId, decision.tabId),
        );
        void persistWrite(() =>
          client.setActiveTab({ windowId, tabId: decision.tabId }),
        );
        // Heal the history tag to the tab we're activating. Normally it
        // already matches (a tagged switch), so `stamp` no-ops.
        stamp(decision.tabId);
        break;
      }
      case "replace": {
        const target = {
          tabId: decision.tabId,
          ...location,
          ...identity,
        };
        // Synchronous local apply keeps re-entrant runs from ever seeing the
        // pre-navigation location.
        applyLocalTransform((s) =>
          setTabTargetLocal(s, { ...target, now: Date.now }),
        );
        void persistWrite(() => client.setTabTarget(target));
        if (decision.stampTabId) stamp(decision.stampTabId);
        break;
      }
      case "open": {
        const input = { windowId, ...location, ...identity };
        // Mint the id here so the local apply and the persisted state agree on
        // it, and so a replayed call is idempotent on the server.
        const mintedId = crypto.randomUUID();
        applyLocalTransform(
          (s) =>
            openTabLocal(s, {
              ...input,
              makeId: () => mintedId,
              now: Date.now,
            }).snapshot,
        );
        void persistWrite(() => client.openTab({ ...input, tabId: mintedId }));
        // Stamp the entry with the tab that now owns this route.
        stamp(mintedId);
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
    locationIsCurrent,
    settledTabId,
    params.channelId,
    params.dashboardId,
    routeChannelSection,
    routeAppView,
    locationHref,
    activeSession.taskId,
    activeSession.channelId,
    routeTitle,
    railPane,
    listOpen,
    scopedSpaceId,
    client,
    router,
  ]);

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
        const taskId = isActive ? (activeSession.taskId ?? null) : t.taskId;
        const dashId = isActive ? (params.dashboardId ?? null) : t.dashboardId;
        const channelId = isActive
          ? (params.channelId ?? activeSession.channelId ?? null)
          : t.channelId;
        const section = isActive ? routeChannelSection : t.channelSection;
        const appView = isActive ? routeAppView : t.appView;
        const channel = channelName(channelId);
        if (taskId) {
          const task = findTask(taskId);
          return {
            id: t.id,
            label:
              task?.title ??
              taskInfo.get(taskId) ??
              t.viewState?.title ??
              "Task",
            // The session list's status dot, so a tab and its row never say
            // different things about the same session.
            icon: <TaskTabDot task={task} />,
            channelName: channel,
            pinned,
          };
        }
        if (dashId) {
          const info = resolveCanvas(dashId);
          return {
            id: t.id,
            label: info?.name ?? t.viewState?.title ?? "Canvas",
            icon: iconForTemplate(info?.templateId ?? "freeform", {
              size: 14,
            }),
            channelName: channel,
            pinned,
          };
        }
        // A channel tab: a sub-section (Recents/CONTEXT.md/…) or the channel home.
        // The section drives the label; the channel name carries the space
        // context. Home has no section, so it labels by the channel name.
        if (channelId) {
          const meta = channelSectionFor(section);
          return {
            id: t.id,
            label:
              meta?.label ??
              channel ??
              t.viewState?.title ??
              (spacesLayout ? "Space" : "Channel"),
            icon: channelGlyph(channel ?? undefined, {
              size: 14,
              space: spacesLayout,
            }),
            channelName: channel,
            // No section meta → the channel's index page.
            isChannelHome: !meta,
            pinned,
          };
        }
        // A top-level app page (Inbox, Agents, Skills, …).
        if (appView && isTabAppView(appView)) {
          return {
            id: t.id,
            label: TAB_APP_VIEW_META[appView].label,
            icon: TAB_APP_VIEW_META[appView].icon,
            channelName: null,
            pinned,
          };
        }
        return {
          id: t.id,
          label: t.viewState?.title ?? "New tab",
          channelName: null,
          pinned,
        };
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
    activeSession.taskId,
    activeSession.channelId,
    routeChannelSection,
    routeAppView,
    spacesLayout,
  ]);

  // Navigate to a tab, tagging the history entry with its id so the switch is
  // replayable by back/forward.
  //
  // The href is where the tab is, so it is what we go back to: it is the only
  // thing that carries search params, and the only thing that covers routes
  // outside the label cache's vocabulary. Rebuilding a canonical route from
  // that cache instead sent every such tab (a loop, an archived list, a space's
  // canvases) to the fallback below on every switch.
  //
  // The reconstruction survives underneath for tabs persisted before hrefs were
  // stored, whose `href` is null until their next navigation.
  const goToTab = useCallback(
    (tab: TabRef) => {
      const state = (prev: object) => ({ ...prev, tabId: tab.id });
      if (tab.href) {
        pushTabHistoryEntry(router.history, tab.href, tab.id);
        return;
      }
      if (tab.taskId && tab.channelId) {
        navigate({
          to: "/spaces/$channelId/tasks/$taskId",
          params: { channelId: tab.channelId, taskId: tab.taskId },
          state,
        });
      } else if (tab.taskId) {
        // A channel-less task tab — the Code task detail route.
        navigate({
          to: "/tasks/$taskId",
          params: { taskId: tab.taskId },
          state,
        });
      } else if (tab.dashboardId && tab.channelId) {
        navigate({
          to: "/spaces/$channelId/dashboards/$dashboardId",
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
            to: `/spaces/$channelId/${section.key}` as const,
            params,
            state,
          });
        } else {
          navigate({ to: "/spaces/$channelId", params, state });
        }
      } else if (tab.appView && isTabAppView(tab.appView)) {
        // A top-level app page — back to its canonical route (literal `to` per
        // case so the router types stay checked).
        switch (tab.appView) {
          case "activity":
            navigate({ to: "/activity", state });
            break;
          case "home":
            navigate({ to: "/", state });
            break;
          case "inbox":
            navigate({
              to: channelReportsEnabled ? "/spaces" : "/inbox",
              state,
            });
            break;
          case "agents":
            navigate({ to: "/agents", state });
            break;
          case "loops":
            navigate({ to: "/loops", state });
            break;
          case "archived":
            navigate({ to: "/archived", state });
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
          case "context":
            navigate({ to: "/context", search: { path: undefined }, state });
            break;
          case "settings":
            navigate({ to: "/settings", state });
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
        navigate({ to: BLANK_TAB_HREF, state });
      }
    },
    [channelReportsEnabled, navigate, router.history],
  );

  const handleSelect = useCallback(
    (tabId: string) => {
      if (!windowId) return;
      const target = readMirror().tabs.find(
        (tab) => tab.windowId === windowId && tab.id === tabId,
      );
      if (target) goToTab(target);
    },
    [goToTab, windowId],
  );

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
    useDraftStore
      .getState()
      .actions.setDraft(getTaskInputSessionId(tabId), null);
    const next = applyLocalTransform((s) => closeTabLocal(s, tabId).snapshot);
    applyCloseResult(next);
    void persistWrite(() => client.close(tabId));
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
    void persistWrite(() => client.setOrder({ windowId, tabIds: order }));
  };

  // Bulk closes operate on the strip's *displayed* order (pinned-first) and
  // never take pinned tabs with them. The anchor (the right-clicked tab, which
  // always survives) takes focus if the active tab was among those closed.
  const handleCloseMany = (tabIds: string[], anchorTabId: string) => {
    if (tabIds.length === 0) return;
    const draftActions = useDraftStore.getState().actions;
    for (const tabId of tabIds) {
      draftActions.setDraft(getTaskInputSessionId(tabId), null);
    }
    const next = applyLocalTransform((s) =>
      closeTabsLocal(s, tabIds, anchorTabId),
    );
    applyCloseResult(next);
    void persistWrite(() =>
      client.closeMany({ tabIds, focusTabId: anchorTabId }),
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

  const landOnDefault = (tabId?: string): void => {
    const state = tabId ? (prev: object) => ({ ...prev, tabId }) : undefined;
    navigate({ to: BLANK_TAB_HREF, state });
  };

  const handleNewTab = (): void => openBrowserTab(BLANK_TAB_HREF);

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
    },
  );

  // Cmd/Ctrl+1-9 switches tabs, the browser way: 1-8 pick that position in the
  // strip, 9 picks the last tab however many there are. Reads the DISPLAYED
  // (pinned-first) order, so the key matches what you are counting on screen.
  //
  // Owned by the strip wherever it is mounted, so a press has one local-first
  // path. On macOS, pure ctrl stays with the task editor's inner tab switcher.
  useHotkeys(
    SHORTCUTS.SWITCH_BROWSER_TAB,
    (event, handler) => {
      if (!shouldHandleBrowserTabSwitch(event, isMac)) return;
      const slot = Number.parseInt(handler.keys?.[0] ?? "", 10);
      if (Number.isNaN(slot) || tabs.length === 0) return;
      const tab = slot === 9 ? tabs[tabs.length - 1] : tabs[slot - 1];
      if (!tab) return;
      handleSelect(tab.id);
    },
    {
      enableOnFormTags: true,
      enableOnContentEditable: true,
      preventDefault: true,
    },
    [tabs, handleSelect],
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
      onNewTab={handleNewTab}
    />
  );
}
