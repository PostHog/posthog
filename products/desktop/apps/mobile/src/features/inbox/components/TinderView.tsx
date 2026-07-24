import { Text } from "@components/text";
import { formatDistanceToNow } from "date-fns";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { Check, GithubLogo, Lightning, X } from "phosphor-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import {
  SafeAreaView,
  useSafeAreaInsets,
} from "react-native-safe-area-context";
import { MarkdownText } from "@/features/chat/components/MarkdownText";
import { usePreferencesStore } from "@/features/preferences/stores/preferencesStore";
import { createTask, runTaskInCloud } from "@/features/tasks/api";
import { DEFAULT_MODEL } from "@/features/tasks/composer/options";
import type {
  CreateTaskOptions,
  RepositoryOption,
} from "@/features/tasks/types";
import {
  ANALYTICS_EVENTS,
  computeReportAgeHours,
  useAnalytics,
} from "@/lib/analytics";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";
import { getReportRepository } from "../api";
import { useDismissedReportsStore } from "../stores/dismissedReportsStore";
import { useInboxStore } from "../stores/inboxStore";
import type {
  SignalReport,
  SignalReportPriority,
  SignalReportStatus,
} from "../types";
import { formatSignalReportSummaryMarkdown, inboxStatusLabel } from "../utils";
import { SwipeableReportCard } from "./SwipeableReportCard";

const log = logger.scope("tinder-view");

// ─── Badge helpers (duplicated from SwipeableReportCard to avoid barrel exports) ───

const statusColorMap: Record<string, { bg: string; text: string }> = {
  ready: { bg: "bg-status-success/20", text: "text-status-success" },
  pending_input: { bg: "bg-accent-3", text: "text-accent-11" },
  in_progress: { bg: "bg-status-warning/20", text: "text-status-warning" },
  candidate: { bg: "bg-status-info/20", text: "text-status-info" },
  potential: { bg: "bg-gray-5/20", text: "text-gray-9" },
  failed: { bg: "bg-status-error/20", text: "text-status-error" },
  suppressed: { bg: "bg-gray-5/20", text: "text-gray-9" },
  deleted: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

const priorityColorMap: Record<
  SignalReportPriority,
  { bg: string; text: string }
> = {
  P0: { bg: "bg-status-error/20", text: "text-status-error" },
  P1: { bg: "bg-status-warning/20", text: "text-status-warning" },
  P2: { bg: "bg-status-info/20", text: "text-status-info" },
  P3: { bg: "bg-gray-5/20", text: "text-gray-9" },
  P4: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

function StatusBadge({ status }: { status: SignalReportStatus }) {
  const colors = statusColorMap[status] ?? statusColorMap.potential;
  return (
    <View className={`rounded-full px-2 py-0.5 ${colors.bg}`}>
      <Text className={`font-medium text-[11px] ${colors.text}`}>
        {inboxStatusLabel(status)}
      </Text>
    </View>
  );
}

function PriorityBadge({ priority }: { priority: SignalReportPriority }) {
  const colors = priorityColorMap[priority] ?? priorityColorMap.P4;
  return (
    <View className={`rounded-full px-2 py-0.5 ${colors.bg}`}>
      <Text className={`font-medium text-[11px] ${colors.text}`}>
        {priority}
      </Text>
    </View>
  );
}

// ─── Empty state ───

function EmptyState() {
  const decidedCount = useDismissedReportsStore(
    (s) => s.dismissedIds.length + s.acceptedIds.length,
  );
  const clearDismissed = useDismissedReportsStore((s) => s.clearDismissed);

  return (
    <View className="items-center gap-3 px-8">
      <Text className="text-[32px]">🎉</Text>
      <Text className="font-semibold text-[17px] text-gray-12">
        All caught up!
      </Text>
      <Text className="text-center text-[14px] text-gray-10">
        You've reviewed all reports assigned to you. Check back later for new
        ones.
      </Text>
      {decidedCount > 0 && (
        <Pressable
          onPress={clearDismissed}
          className="mt-2 rounded-full border border-gray-6 bg-gray-2 px-4 py-2 active:bg-gray-3"
        >
          <Text className="text-[13px] text-gray-11">
            Reset {decidedCount} reviewed
          </Text>
        </Pressable>
      )}
    </View>
  );
}

// ─── Main component ───

interface TinderViewProps {
  reports: SignalReport[];
  repositoryOptions: RepositoryOption[];
  isLoading?: boolean;
}

export function TinderView({
  reports,
  repositoryOptions,
  isLoading,
}: TinderViewProps) {
  const themeColors = useThemeColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  // Store state
  const currentIndex = useInboxStore((s) => s.currentIndex);
  const _advanceCard = useInboxStore((s) => s.advanceCard);
  const dismissReport = useDismissedReportsStore((s) => s.dismissReport);
  const acceptReport = useDismissedReportsStore((s) => s.acceptReport);

  const analytics = useAnalytics();

  const trackReportAction = useCallback(
    (
      report: SignalReport,
      actionType: "dismiss" | "create_pr",
      position: number,
      total: number,
    ) => {
      analytics.track(ANALYTICS_EVENTS.INBOX_REPORT_ACTION, {
        report_id: report.id,
        report_title: report.title ?? null,
        report_age_hours: computeReportAgeHours(report.created_at),
        priority: report.priority ?? null,
        actionability: report.actionability ?? null,
        action_type: actionType,
        // Tinder cards stack like a list of rows the user is acting on
        // without opening a detail view — closest desktop analogue.
        surface: "list_row",
        is_bulk: false,
        bulk_size: 1,
        rank: position,
        list_size: total,
      });
    },
    [analytics],
  );

  // Local state
  const [expandedReport, setExpandedReport] = useState<SignalReport | null>(
    null,
  );
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{
    taskId: string | null;
    title: string;
    pending: boolean;
  } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToastPending = useCallback((title: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ taskId: null, title, pending: true });
  }, []);

  const showToastDone = useCallback((taskId: string, title: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ taskId, title, pending: false });
    toastTimer.current = setTimeout(() => setToast(null), 10_000);
  }, []);

  const reportsRef = useRef(reports);
  reportsRef.current = reports;

  const handleDismiss = useCallback(
    (reportId: string) => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      const visible = reportsRef.current;
      const idx = visible.findIndex((r) => r.id === reportId);
      const target = idx >= 0 ? visible[idx] : null;
      if (target) trackReportAction(target, "dismiss", idx, visible.length);
      dismissReport(reportId);
      // Don't advanceCard() — the parent filters dismissed IDs from the
      // reports array, so removing the report shifts the next one into
      // the current index position automatically.
    },
    [dismissReport, trackReportAction],
  );

  const handleAccept = useCallback(
    async (report: SignalReport) => {
      setCreating(true);
      setError(null);
      showToastPending(report.title ?? "Untitled report");
      // Snapshot rank/list_size before the swipe completes — accepting filters
      // the report out of the visible deck.
      const visibleBefore = reportsRef.current;
      const acceptedRank = visibleBefore.findIndex((r) => r.id === report.id);
      const acceptedListSize = visibleBefore.length;
      try {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

        // 1. Get the repo from the report artefacts
        const repo = await getReportRepository(report.id);

        // 2. Find matching repository option to get integrationId
        const match = repo
          ? repositoryOptions.find(
              (o) => o.repository.toLowerCase() === repo.toLowerCase(),
            )
          : null;

        // 3. Create the task
        const prompt = `Act on this signal report. Investigate the root cause, implement the fix, and open a PR if appropriate.\n\n${report.summary ?? ""}`;
        const task = await createTask({
          description: prompt,
          title: prompt.slice(0, 255),
          repository: match?.repository ?? repo ?? undefined,
          github_integration: match?.integrationId ?? undefined,
          origin_product: "signal_report",
          signal_report: report.id,
          signal_report_task_relationship: "implementation",
        } as CreateTaskOptions);

        // 4. Run it
        await runTaskInCloud(task.id, {
          pendingUserMessage: prompt,
          runtimeAdapter: "claude",
          model: DEFAULT_MODEL,
          initialPermissionMode: "plan",
          runSource: "signal_report",
          signalReportId: report.id,
          rtkEnabled: usePreferencesStore.getState().rtkEnabledCloud,
        });

        acceptReport(report.id);
        trackReportAction(report, "create_pr", acceptedRank, acceptedListSize);
        showToastDone(task.id, report.title ?? "Untitled report");
      } catch (e) {
        const message =
          e instanceof Error ? e.message : "Failed to create task";
        log.error("Accept failed", message);
        setError(message);
        setToast(null);
      } finally {
        setCreating(false);
      }
    },
    [
      repositoryOptions,
      showToastPending,
      showToastDone,
      acceptReport,
      trackReportAction,
    ],
  );

  const currentReport =
    currentIndex < reports.length ? reports[currentIndex] : null;

  // ── Repo resolution ────────────────────────────────────────────────────────
  const [repoMap, setRepoMap] = useState<Record<string, string | null>>({});
  const fetchingRef = useRef<Set<string>>(new Set());

  // Lazily resolve repos for the next few visible cards
  useEffect(() => {
    const upcoming = reports.slice(currentIndex, currentIndex + 3);
    for (const r of upcoming) {
      if (r.id in repoMap || fetchingRef.current.has(r.id)) continue;
      fetchingRef.current.add(r.id);
      getReportRepository(r.id)
        .then((repo) => setRepoMap((prev) => ({ ...prev, [r.id]: repo })))
        .catch(() => setRepoMap((prev) => ({ ...prev, [r.id]: null })))
        .finally(() => fetchingRef.current.delete(r.id));
    }
  }, [reports, currentIndex, repoMap]);

  const STACK_OFFSET = 12; // px between each stacked card
  const MAX_VISIBLE = 3;

  return (
    <View className="flex-1">
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator size="large" color={themeColors.accent[9]} />
          <Text className="mt-3 text-[13px] text-gray-9">
            Loading reports...
          </Text>
        </View>
      ) : !currentReport ? (
        <View className="flex-1 items-center justify-center">
          <EmptyState />
        </View>
      ) : (
        <View className="flex-1 px-4 pt-2 pb-4">
          <View className="relative flex-[0.9]">
            {reports
              .slice(currentIndex, currentIndex + MAX_VISIBLE)
              .reverse()
              .map((report, i, arr) => {
                const depth = arr.length - 1 - i;
                return (
                  <SwipeableReportCard
                    key={report.id}
                    report={report}
                    onDismiss={handleDismiss}
                    onAccept={handleAccept}
                    onExpand={setExpandedReport}
                    isTopCard={depth === 0}
                    stackOffset={depth * STACK_OFFSET}
                    repo={repoMap[report.id]}
                  />
                );
              })}
          </View>
        </View>
      )}

      {/* Error display */}
      {error && (
        <View className="mx-4 mb-4 rounded-lg bg-status-error/10 px-3 py-2">
          <Text className="text-[13px] text-status-error">{error}</Text>
        </View>
      )}

      {/* "Task started" toast — sits above the mode switcher pill */}
      {toast && (
        <Pressable
          onPress={() => {
            if (toast.pending || !toast.taskId) return;
            setToast(null);
            router.push(`/task/${toast.taskId}`);
          }}
          disabled={toast.pending}
          className="elevation-4 absolute inset-x-4 flex-row items-center justify-between rounded-2xl bg-status-success px-5 py-4 shadow-lg active:opacity-80"
          style={{ bottom: insets.bottom + 76 }}
        >
          <View className="min-w-0 flex-1">
            <Text className="font-semibold text-[15px] text-white">
              {toast.pending ? "Starting task\u2026" : "Task started"}
            </Text>
            <Text
              className="mt-0.5 text-[13px] text-white/80"
              numberOfLines={1}
            >
              {toast.title}
            </Text>
          </View>
          {toast.pending ? (
            <ActivityIndicator className="ml-3" color="white" size="small" />
          ) : (
            <Text className="ml-3 font-semibold text-[14px] text-white">
              View →
            </Text>
          )}
        </Pressable>
      )}

      {/* Expanded report modal */}
      <Modal
        visible={!!expandedReport}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setExpandedReport(null)}
      >
        {expandedReport && (
          <View className="flex-1 bg-background">
            <SafeAreaView edges={["top"]} className="flex-1">
              {/* Header with close button */}
              <View className="flex-row items-center justify-between border-gray-6 border-b px-4 py-3">
                <Text
                  className="flex-1 font-semibold text-[17px] text-gray-12"
                  numberOfLines={1}
                >
                  {expandedReport.title ?? "Untitled report"}
                </Text>
                <Pressable
                  onPress={() => setExpandedReport(null)}
                  hitSlop={10}
                  className="pl-3 active:opacity-70"
                >
                  <X size={20} color={themeColors.gray[11]} />
                </Pressable>
              </View>

              {/* Scrollable content */}
              <ScrollView
                className="flex-1"
                contentContainerStyle={{ padding: 16, paddingBottom: 100 }}
              >
                {/* Badges */}
                <View className="mb-3 flex-row flex-wrap items-center gap-1.5">
                  <StatusBadge status={expandedReport.status} />
                  {expandedReport.priority && (
                    <PriorityBadge priority={expandedReport.priority} />
                  )}
                </View>

                {/* Summary */}
                {expandedReport.summary && (
                  <MarkdownText
                    content={formatSignalReportSummaryMarkdown(
                      expandedReport.summary,
                    )}
                  />
                )}

                {/* Signal count + time */}
                <View className="mt-4 flex-row items-center gap-3">
                  <View className="flex-row items-center gap-1">
                    <Lightning
                      size={13}
                      color={themeColors.gray[9]}
                      weight="fill"
                    />
                    <Text className="text-[12px] text-gray-9">
                      {expandedReport.signal_count} signal
                      {expandedReport.signal_count !== 1 ? "s" : ""}
                    </Text>
                  </View>
                  <Text className="text-[12px] text-gray-9">
                    Updated{" "}
                    {formatDistanceToNow(new Date(expandedReport.updated_at), {
                      addSuffix: true,
                    })}
                  </Text>
                </View>

                {/* Repo pill */}
                {repoMap[expandedReport.id] && (
                  <View className="mt-4 flex-row">
                    <View className="flex-row items-center gap-1.5 rounded-full border border-gray-6 bg-gray-2 px-2.5 py-1">
                      <GithubLogo
                        size={12}
                        color={themeColors.gray[9]}
                        weight="fill"
                      />
                      <Text className="text-[11px] text-gray-9">
                        {repoMap[expandedReport.id]}
                      </Text>
                    </View>
                  </View>
                )}
              </ScrollView>

              {/* Bottom action buttons */}
              <View className="absolute inset-x-0 bottom-0 flex-row items-center justify-center gap-8 border-gray-6 border-t bg-background pt-4 pb-8">
                <Pressable
                  onPress={() => {
                    handleDismiss(expandedReport.id);
                    setExpandedReport(null);
                  }}
                  className="h-16 w-16 items-center justify-center rounded-full border-2 border-status-error bg-status-error/10 active:bg-status-error/20"
                  hitSlop={8}
                >
                  <X size={28} color={themeColors.status.error} weight="bold" />
                </Pressable>
                <Pressable
                  onPress={() => {
                    handleAccept(expandedReport);
                    setExpandedReport(null);
                  }}
                  className="h-16 w-16 items-center justify-center rounded-full border-2 border-status-success bg-status-success/10 active:bg-status-success/20"
                  disabled={creating}
                  hitSlop={8}
                >
                  {creating ? (
                    <ActivityIndicator color={themeColors.status.success} />
                  ) : (
                    <Check
                      size={28}
                      color={themeColors.status.success}
                      weight="bold"
                    />
                  )}
                </Pressable>
              </View>
            </SafeAreaView>
          </View>
        )}
      </Modal>
    </View>
  );
}
