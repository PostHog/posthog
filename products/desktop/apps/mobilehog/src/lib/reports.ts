import {
  buildCreatePrReportPrompt,
  canCreateImplementationPr,
} from "@posthog/core/inbox/reportActions";
import {
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import type {
  SignalReport,
  SignalReportArtefactsResponse,
  SignalReportSignalsResponse,
} from "@posthog/shared/domain-types";
import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { create } from "zustand";
import { accountStorageKey, sessionIdentity, useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";
import { currentRunConfig } from "@/lib/composer";
import { type ReportSort, usePrefs } from "@/lib/prefs";
import { deviceWorkspace } from "@/lib/storage";

export const REPORT_SORTS: Record<
  ReportSort,
  { label: string; ordering: string }
> = {
  newest: { label: "Newest first", ordering: "-created_at,-id" },
  oldest: { label: "Oldest first", ordering: "created_at,id" },
  priority: { label: "Priority", ordering: "priority,-created_at,-id" },
  updated: { label: "Recently updated", ordering: "-updated_at,-id" },
};

export const reportKeys = {
  all: ["reports"] as const,
  list: ["reports", "list"] as const,
  signals: (id: string) => ["reports", id, "signals"] as const,
  artefacts: (id: string) => ["reports", id, "artefacts"] as const,
};

// Inbox and its badge use the same reviewer filter.
export type ReportView = "active" | "unread" | "history";

export function useReports(view: ReportView = "active", search = "") {
  const session = useAuth((s) => s.session);
  const queryClient = useQueryClient();
  const sort = usePrefs((s) => s.reportSort);
  return useInfiniteQuery({
    queryKey: [...reportKeys.list, sort, view, search],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const client = getClient();
      const user = await queryClient.fetchQuery({
        queryKey: ["current-user"],
        queryFn: async () => ({ uuid: (await client.getCurrentUser()).uuid }),
        staleTime: 5 * 60_000,
      });
      if (!user.uuid)
        throw new Error("Could not identify your account. Try again.");
      const page = await client.getSignalReports({
        status:
          view === "history"
            ? "suppressed,resolved"
            : INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
        actionability:
          view === "history"
            ? undefined
            : INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
        search: search || undefined,
        suggested_reviewers: user.uuid,
        ordering: (REPORT_SORTS[sort] ?? REPORT_SORTS.newest).ordering,
        limit: 50,
        offset: pageParam,
      });
      void useSeenReports
        .getState()
        .sync(page.results.map((report) => report.id))
        .catch(() => {});
      return page;
    },
    getNextPageParam: (lastPage, pages) => {
      const loaded = pages.reduce(
        (total, page) => total + page.results.length,
        0,
      );
      return lastPage.results.length > 0 && loaded < lastPage.count
        ? loaded
        : undefined;
    },
    enabled: !!session,
    refetchInterval: 60_000,
    select: (data) =>
      data.pages
        .flatMap((page) => page.results)
        .filter(
          (report) => view === "history" || canCreateImplementationPr(report),
        ),
  });
}

export function useReportDetail(id: string) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["reports", id, "detail"],
    placeholderData: () =>
      queryClient
        .getQueriesData<InfiniteData<{ results: SignalReport[] }>>({
          queryKey: reportKeys.list,
        })
        .flatMap(
          ([, data]) => data?.pages.flatMap((page) => page.results) ?? [],
        )
        .find((report) => report.id === id),
    queryFn: async () => {
      const report = await getClient().getSignalReport(id);
      if (!report) throw new Error("Report is no longer available.");
      return report;
    },
    staleTime: 60_000,
    enabled: !!id,
  });
}

export function useReportSignals(reportId: string | null) {
  return useQuery<SignalReportSignalsResponse>({
    queryKey: reportKeys.signals(reportId ?? ""),
    queryFn: () => getClient().getSignalReportSignals(reportId ?? ""),
    enabled: !!reportId,
    staleTime: 5 * 60_000,
  });
}

export function useReportArtefacts(reportId: string | null) {
  return useQuery<SignalReportArtefactsResponse>({
    queryKey: reportKeys.artefacts(reportId ?? ""),
    queryFn: () => getClient().getSignalReportArtefacts(reportId ?? ""),
    enabled: !!reportId,
    staleTime: 5 * 60_000,
  });
}

export function useDismissReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reportId: string) =>
      getClient().updateSignalReportState(reportId, { state: "suppressed" }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: reportKeys.all }),
  });
}

// Swipe right: open a task on the report's repo and start the agent on it.
export function useStartReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (report: SignalReport) => {
      const config = currentRunConfig();
      const client = getClient();
      const prompt = buildCreatePrReportPrompt({ reportId: report.id });
      // The server picks the repository from the report's repo selection.
      const task = await client.createTask({
        description: prompt,
        title: (report.title ?? "Signal report").slice(0, 255),
        origin_product: "signal_report",
        signal_report: report.id,
        signal_report_task_relationship: "implementation",
      });
      return client.runTaskInCloud(task.id, undefined, {
        pendingUserMessage: prompt,
        runSource: "signal_report",
        signalReportId: report.id,
        ...config,
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: reportKeys.all });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

// Keep read changes on the device until the server acknowledges them.
const SEEN_KEY = "mobilehog_seen_reports";
const SEEN_CAP = 500;
let seenWrite = Promise.resolve();
let seenVersion = 0;
let syncing: string | null = null;
const queuedSyncs = new Map<string, Set<string>>();
let retryAfter = 0;
let retryIdentity: string | null = null;

type SavedReadState = { seen: string[]; pending: Record<string, boolean> };
interface SeenState {
  seen: Set<string>;
  pending: Record<string, boolean>;
  hydrated: boolean;
  syncError: boolean;
  hydrate: () => Promise<void>;
  markSeen: (ids: string[], read?: boolean) => Promise<void>;
  sync: (ids: string[]) => Promise<void>;
}

export const useSeenReports = create<SeenState>((set, get) => ({
  seen: new Set(),
  pending: {},
  hydrated: false,
  syncError: false,
  hydrate: async () => {
    if (!useAuth.getState().session || get().hydrated) return;
    const identity = sessionIdentity();
    const saved = await deviceWorkspace().read<SavedReadState>(
      "report-read-state",
      Infinity,
    );
    const legacy =
      saved || Platform.OS === "web"
        ? null
        : await SecureStore.getItemAsync(accountStorageKey(SEEN_KEY));
    if (sessionIdentity() !== identity || get().hydrated) return;
    set({
      seen: new Set(
        saved?.seen ?? (legacy ? (JSON.parse(legacy) as string[]) : []),
      ),
      pending: saved?.pending ?? {},
      hydrated: true,
    });
  },
  sync: async (ids) => {
    const identity = sessionIdentity();
    if (
      !useAuth.getState().session ||
      (retryIdentity === identity && Date.now() < retryAfter)
    )
      return;
    if (syncing === identity) {
      const queued = queuedSyncs.get(identity) ?? new Set<string>();
      for (const id of ids) queued.add(id);
      queuedSyncs.set(identity, queued);
      return;
    }
    syncing = identity;
    try {
      await get().hydrate();
      if (sessionIdentity() !== identity) return;
      const version = seenVersion;
      const pending = { ...get().pending };
      if (!ids.length && !Object.keys(pending).length) return;
      const client = getClient();
      for (const read of [true, false]) {
        const changes = Object.keys(pending).filter(
          (id) => pending[id] === read,
        );
        for (let offset = 0; offset < changes.length; offset += 100)
          await client.getReportReadStates(
            changes.slice(offset, offset + 100),
            read,
          );
      }
      const states: Record<string, boolean> = {};
      for (let offset = 0; offset < ids.length; offset += 100)
        Object.assign(
          states,
          await client.getReportReadStates(ids.slice(offset, offset + 100)),
        );
      const workspace = deviceWorkspace();
      const write = seenWrite
        .catch(() => {})
        .then(async () => {
          if (sessionIdentity() !== identity || seenVersion !== version) return;
          const next = new Set(get().seen);
          for (const [id, read] of Object.entries(states)) {
            if (read) next.add(id);
            else next.delete(id);
          }
          const seen = [...next].slice(-SEEN_CAP);
          await workspace.write("report-read-state", { seen, pending: {} });
          if (sessionIdentity() === identity)
            set({ seen: new Set(seen), pending: {}, syncError: false });
        });
      seenWrite = write;
      await write;
      retryAfter = 0;
    } catch {
      if (sessionIdentity() === identity) {
        retryIdentity = identity;
        retryAfter = Date.now() + 60_000;
        set({ syncError: true });
      }
    } finally {
      if (syncing === identity) syncing = null;
      const queued = queuedSyncs.get(identity);
      queuedSyncs.delete(identity);
      if (sessionIdentity() === identity && queued?.size)
        void get().sync([...queued]);
    }
  },
  markSeen: async (ids, read = true) => {
    const identity = sessionIdentity();
    if (!useAuth.getState().session || !ids.length) return;
    const workspace = deviceWorkspace();
    const write = seenWrite
      .catch(() => {})
      .then(async () => {
        await get().hydrate();
        if (sessionIdentity() !== identity) return;
        seenVersion++;
        const next = new Set(get().seen);
        const pending = { ...get().pending };
        for (const id of ids) {
          next.delete(id);
          if (read) next.add(id);
          pending[id] = read;
        }
        const seen = [...next].slice(-SEEN_CAP);
        await workspace.write("report-read-state", { seen, pending });
        if (sessionIdentity() === identity)
          set({ seen: new Set(seen), pending });
      });
    seenWrite = write;
    await write;
    if (sessionIdentity() === identity) void get().sync(ids);
  },
}));
