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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as SecureStore from "expo-secure-store";
import { create } from "zustand";
import { useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";
import { currentRunConfig } from "@/lib/composer";

export const reportKeys = {
  all: ["reports"] as const,
  list: ["reports", "list"] as const,
  signals: (id: string) => ["reports", id, "signals"] as const,
  artefacts: (id: string) => ["reports", id, "artefacts"] as const,
};

// Reports a person can act on right now, highest priority first.
export function useReports() {
  const session = useAuth((s) => s.session);
  return useQuery({
    queryKey: reportKeys.list,
    queryFn: () =>
      getClient().getSignalReports({
        status: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
        actionability: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
        ordering: "status,-priority,-created_at",
        limit: 100,
      }),
    enabled: !!session,
    refetchInterval: 60_000,
    select: (page) =>
      page.results.filter((report) => canCreateImplementationPr(report)),
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
        ...currentRunConfig(),
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: reportKeys.all });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

// Which reports this device has already surfaced in triage, so only new ones
// pop the deck automatically.
const SEEN_KEY = "mobilehog_seen_reports";
const SEEN_CAP = 500;

interface SeenState {
  seen: Set<string>;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  markSeen: (ids: string[]) => Promise<void>;
}

export const useSeenReports = create<SeenState>((set, get) => ({
  seen: new Set(),
  hydrated: false,
  hydrate: async () => {
    try {
      const raw = await SecureStore.getItemAsync(SEEN_KEY);
      set({
        seen: new Set(raw ? (JSON.parse(raw) as string[]) : []),
        hydrated: true,
      });
    } catch {
      set({ hydrated: true });
    }
  },
  markSeen: async (ids) => {
    const next = new Set(get().seen);
    for (const id of ids) next.add(id);
    const list = [...next].slice(-SEEN_CAP);
    set({ seen: new Set(list) });
    await SecureStore.setItemAsync(SEEN_KEY, JSON.stringify(list));
  },
}));
