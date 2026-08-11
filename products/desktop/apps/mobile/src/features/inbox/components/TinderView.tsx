import { Text } from "@components/text";
import { formatSignalReportSummaryMarkdown } from "@posthog/core/inbox/reportPresentation";
import { getModelConfigOption } from "@posthog/core/task-detail/composerControls";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  GithubLogo,
  Lightning,
  X,
} from "phosphor-react-native";
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
import { useCloudTaskConfigOptions } from "@/features/tasks/hooks/useCloudTaskConfigOptions";
import type {
  CreateTaskOptions,
  RepositoryOption,
} from "@/features/tasks/types";
import {
  ANALYTICS_EVENTS,
  computeReportAgeHours,
  useAnalytics,
} from "@/lib/analytics";
import { formatRelativeTime } from "@/lib/format";
import { logger } from "@/lib/logger";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { useThemeColors } from "@/lib/theme";
import { getReportRepository } from "../api";
import { inboxCardViewBottomInset } from "../cardViewLayout";
import { useDismissReport } from "../hooks/useInboxReports";
import { useDismissedReportsStore } from "../stores/dismissedReportsStore";
import { useInboxStore } from "../stores/inboxStore";
import { ActionabilityBadge, PriorityBadge, StatusBadge } from "./ReportBadges";
import { SwipeableReportCard } from "./SwipeableReportCard";

const log = logger.scope("tinder-view");

/** Vertical px between each card in the stack — cards behind sit lower. */
const STACK_OFFSET = 12;
/** How many cards of the deck are rendered at once. */
const MAX_VISIBLE = 3;
/**
 * The deepest card hangs `STACK_OFFSET * (MAX_VISIBLE - 1)` px below the deck
 * container, so the deck reserves exactly that much space beneath itself for
 * the stack to bleed into without colliding with the hint row.
 */
const STACK_BLEED = STACK_OFFSET * (MAX_VISIBLE - 1);

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
  const { configOptions, isConfigReady } = useCloudTaskConfigOptions("claude");
  const model = getModelConfigOption(configOptions).currentValue;

  // Store state
  const currentIndex = useInboxStore((s) => s.currentIndex);
  const _advanceCard = useInboxStore((s) => s.advanceCard);
  const dismissReport = useDismissedReportsStore((s) => s.dismissReport);
  const undismissReport = useDismissedReportsStore((s) => s.undismissReport);
  const acceptReport = useDismissedReportsStore((s) => s.acceptReport);
  // `mutate` is a stable reference; the mutation result object is not, and
  // would defeat handleDismiss's memoization.
  const { mutate: dismissOnServer } = useDismissReport();

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
      // Propagate to the server so the report doesn't stay open on other
      // devices; a suppressed report can be restored from the archive view.
      // On failure (offline, state transition rejected) roll back the local
      // dismissal so the card returns instead of being hidden on this device
      // while still open everywhere else.
      dismissOnServer(
        {
          reportId,
          reason: "other",
          note: "Dismissed via mobile card swipe",
        },
        {
          onError: (err) => {
            undismissReport(reportId);
            log.warn("Server dismissal failed; restored card", {
              reportId,
              error: err.message,
            });
          },
        },
      );
      // Don't advanceCard() — the parent filters dismissed IDs from the
      // reports array, so removing the report shifts the next one into
      // the current index position automatically.
    },
    [dismissReport, undismissReport, dismissOnServer, trackReportAction],
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
        const client = getPostHogApiClient();
        const task = await client.createTask({
          description: prompt,
          title: prompt.slice(0, 255),
          repository: match?.repository ?? repo ?? undefined,
          github_integration: match?.integrationId ?? undefined,
          origin_product: "signal_report",
          signal_report: report.id,
          signal_report_task_relationship: "implementation",
        } as CreateTaskOptions);

        // 4. Run it
        await client.runTaskInCloud(task.id, undefined, {
          pendingUserMessage: prompt,
          adapter: "claude",
          model,
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
      model,
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

  // The deck ends where the toggle pill's clearance begins; the hint row is the
  // last thing in flow above it. The parent screen has already padded the top
  // past the header fade, so the whole view sits between the two chrome bands.
  const bottomInset = inboxCardViewBottomInset(insets.bottom);

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
        <View
          className="flex-1 px-4 pt-2"
          style={{ paddingBottom: bottomInset }}
        >
          <View
            className="relative flex-1"
            style={{ marginBottom: STACK_BLEED }}
          >
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

          {/* Which way is which, before the first drag teaches it. Anchored to
              the bottom of the view — the container's paddingBottom keeps it
              clear of the safe area and the floating toggle pill. */}
          <View className="mt-3 flex-row items-center justify-between px-1">
            <View className="flex-row items-center gap-1.5">
              <ArrowLeft size={13} color={themeColors.gray[9]} weight="bold" />
              <Text className="text-[12px] text-gray-9">Dismiss</Text>
            </View>
            <View className="flex-row items-center gap-1.5">
              <Text className="text-[12px] text-gray-9">Start task</Text>
              <ArrowRight size={13} color={themeColors.gray[9]} weight="bold" />
            </View>
          </View>
        </View>
      )}

      {/* Error display — floats in the same band as the toast rather than
          appending to the deck's flow, where it would land under the pill. */}
      {error && (
        <View
          className="absolute inset-x-4 rounded-lg bg-status-error/10 px-3 py-2"
          style={{ bottom: bottomInset }}
        >
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
          style={{ bottom: bottomInset }}
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
                  {expandedReport.priority && (
                    <PriorityBadge priority={expandedReport.priority} />
                  )}
                  <StatusBadge status={expandedReport.status} />
                  {expandedReport.actionability && (
                    <ActionabilityBadge value={expandedReport.actionability} />
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
                    {formatRelativeTime(Date.parse(expandedReport.updated_at))}
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
                  disabled={creating || !isConfigReady}
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
