import { Text } from "@components/text";
import { differenceInHours, format, formatDistanceToNow } from "date-fns";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  CaretDown,
  CaretRight,
  ChatCircle,
  Lightning,
  Play,
  Plus,
  ThumbsDown,
  Warning,
} from "phosphor-react-native";
import { usePostHog } from "posthog-react-native";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useUserQuery } from "@/features/auth";
import { MarkdownText } from "@/features/chat/components/MarkdownText";
import { getReportRepository } from "@/features/inbox/api";
import { buildCreatePrReportPrompt } from "@/features/inbox/buildCreatePrReportPrompt";
import { CreatePrFeedbackSheet } from "@/features/inbox/components/CreatePrFeedbackSheet";
import { DiscussReportSheet } from "@/features/inbox/components/DiscussReportSheet";
import {
  type DismissReportResult,
  DismissReportSheet,
} from "@/features/inbox/components/DismissReportSheet";
import { ReportActivity } from "@/features/inbox/components/ReportActivity";
import { SignalCard } from "@/features/inbox/components/SignalCard";
import {
  type ReviewerActionExtra,
  SuggestedReviewers,
} from "@/features/inbox/components/SuggestedReviewers";
import { DISMISSAL_REASON_OPTIONS } from "@/features/inbox/constants";
import { useInboxEngagementTracker } from "@/features/inbox/hooks/useInboxEngagementTracker";
import {
  useInboxReport,
  useInboxReportArtefacts,
  useInboxReportSignals,
} from "@/features/inbox/hooks/useInboxReports";
import { useInboxStore } from "@/features/inbox/stores/inboxStore";
import type {
  ActionabilityJudgmentContent,
  SignalFindingContent,
  SignalReportPriority,
  SignalReportStatus,
  SuggestedReviewersArtefact,
} from "@/features/inbox/types";
import {
  formatSignalReportSummaryMarkdown,
  inboxStatusLabel,
} from "@/features/inbox/utils";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import {
  computeReportAgeHours,
  type InboxReportActionType,
  useAnalytics,
} from "@/lib/analytics";
import { useThemeColors } from "@/lib/theme";

const statusColorMap: Record<string, { bg: string; text: string }> = {
  ready: { bg: "bg-status-success/20", text: "text-status-success" },
  pending_input: { bg: "bg-accent-3", text: "text-accent-11" },
  in_progress: { bg: "bg-status-warning/20", text: "text-status-warning" },
  candidate: { bg: "bg-status-info/20", text: "text-status-info" },
  potential: { bg: "bg-gray-5/20", text: "text-gray-9" },
  failed: { bg: "bg-status-error/20", text: "text-status-error" },
  resolved: { bg: "bg-status-success/20", text: "text-status-success" },
  suppressed: { bg: "bg-gray-5/20", text: "text-gray-9" },
  deleted: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

const priorityColorMap: Record<string, { bg: string; text: string }> = {
  P0: { bg: "bg-status-error/20", text: "text-status-error" },
  P1: { bg: "bg-status-warning/20", text: "text-status-warning" },
  P2: { bg: "bg-status-warning/20", text: "text-status-warning" },
  P3: { bg: "bg-gray-5/20", text: "text-gray-9" },
  P4: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

const actionabilityColorMap: Record<string, { bg: string; text: string }> = {
  immediately_actionable: {
    bg: "bg-status-success/20",
    text: "text-status-success",
  },
  requires_human_input: {
    bg: "bg-status-warning/20",
    text: "text-status-warning",
  },
  not_actionable: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

const actionabilityLabel: Record<string, string> = {
  immediately_actionable: "Actionable",
  requires_human_input: "Needs input",
  not_actionable: "Not actionable",
};

function StatusBadge({ status }: { status: SignalReportStatus }) {
  const colors = statusColorMap[status] ?? statusColorMap.potential;
  return (
    <View className={`rounded px-2 py-1 ${colors.bg}`}>
      <Text className={`font-medium text-[12px] ${colors.text}`}>
        {inboxStatusLabel(status)}
      </Text>
    </View>
  );
}

function PriorityBadge({ priority }: { priority: SignalReportPriority }) {
  const colors = priorityColorMap[priority] ?? priorityColorMap.P3;
  return (
    <View className={`rounded px-2 py-1 ${colors.bg}`}>
      <Text className={`font-medium text-[12px] ${colors.text}`}>
        {priority}
      </Text>
    </View>
  );
}

function ActionabilityBadge({ value }: { value: string }) {
  const colors =
    actionabilityColorMap[value] ?? actionabilityColorMap.not_actionable;
  const label = actionabilityLabel[value] ?? value;
  return (
    <View className={`rounded px-2 py-1 ${colors.bg}`}>
      <Text className={`font-medium text-[12px] ${colors.text}`}>{label}</Text>
    </View>
  );
}

export default function ReportDetailScreen() {
  // Catch-all route: `id` arrives as string[] for `/inbox/<uuid>/<slug>` and
  // we only read the first segment (the UUID). The slug is purely cosmetic;
  // receivers ignore everything past the UUID, matching the desktop contract
  // in `apps/code/src/shared/deeplink.ts`. Expo-router can hand us either a
  // string or string[] depending on the URL shape, so tolerate both.
  const { id: idParam } = useLocalSearchParams<{ id: string | string[] }>();
  const reportId = Array.isArray(idParam) ? idParam[0] : idParam;
  const router = useRouter();
  const themeColors = useThemeColors();
  const insets = useSafeAreaInsets();
  const posthog = usePostHog();
  const { data: report, isLoading, error } = useInboxReport(reportId ?? null);
  const { data: me } = useUserQuery();
  const [reportRepo, setReportRepo] = useState<string | null>(null);
  const [dismissOpen, setDismissOpen] = useState(false);
  const [discussOpen, setDiscussOpen] = useState(false);
  const [createPrFeedbackOpen, setCreatePrFeedbackOpen] = useState(false);
  const [signalsExpanded, setSignalsExpanded] = useState(false);

  const artefactsQuery = useInboxReportArtefacts(reportId ?? null);
  const signalsQuery = useInboxReportSignals(reportId ?? null);

  // ── Engagement analytics ────────────────────────────────────────────────
  const analytics = useAnalytics();
  const lastVisibleReportIds = useInboxStore((s) => s.lastVisibleReportIds);
  const previousOpenedReportId = useInboxStore((s) => s.previousOpenedReportId);
  const setPreviousOpenedReportId = useInboxStore(
    (s) => s.setPreviousOpenedReportId,
  );
  const rank = useMemo(() => {
    if (!reportId) return -1;
    const idx = lastVisibleReportIds.indexOf(reportId);
    return idx;
  }, [reportId, lastVisibleReportIds]);
  const listSize = lastVisibleReportIds.length;
  const tracker = useInboxEngagementTracker({
    analytics,
    report: report ?? null,
    rank,
    listSize,
    openMethod: "click",
    previousReportId: previousOpenedReportId,
  });
  // Remember this report as the "previous" once it's been opened so the next
  // OPENED event can chain to it.
  useEffect(() => {
    if (!reportId) return;
    setPreviousOpenedReportId(reportId);
  }, [reportId, setPreviousOpenedReportId]);

  const handleScroll = useCallback(
    (_event: NativeSyntheticEvent<NativeScrollEvent>) => {
      tracker.signalScroll();
    },
    [tracker],
  );

  const fireReviewerAction = useCallback(
    (action_type: InboxReportActionType, extra?: ReviewerActionExtra) => {
      if (!report) return;
      tracker.signalAction({
        report_id: report.id,
        report_title: report.title ?? null,
        report_age_hours: computeReportAgeHours(report.created_at),
        action_type,
        surface: "detail_pane",
        is_bulk: false,
        bulk_size: 1,
        ...extra,
      });
    },
    [report, tracker],
  );

  const handleToggleSignals = useCallback(() => {
    // Fire analytics outside the state updater — Strict Mode double-invokes
    // updaters in development, which would double-fire the event.
    const next = !signalsExpanded;
    if (next && report) {
      tracker.signalAction({
        report_id: report.id,
        report_title: report.title ?? null,
        report_age_hours: computeReportAgeHours(report.created_at),
        action_type: "expand_signal",
        surface: "detail_pane",
        is_bulk: false,
        bulk_size: 1,
      });
    }
    setSignalsExpanded(next);
  }, [report, tracker, signalsExpanded]);

  useEffect(() => {
    if (!reportId) return;
    let cancelled = false;
    getReportRepository(reportId)
      .then((repo) => {
        if (!cancelled) setReportRepo(repo);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  // ── Derive artefact bits ────────────────────────────────────────────────
  const artefacts = artefactsQuery.data?.results ?? [];

  const actionabilityJudgment =
    useMemo((): ActionabilityJudgmentContent | null => {
      for (const a of artefacts) {
        if (a.type === "actionability_judgment") {
          return a.content as ActionabilityJudgmentContent;
        }
      }
      return null;
    }, [artefacts]);

  const reviewerArtefact = useMemo((): SuggestedReviewersArtefact | null => {
    for (const a of artefacts) {
      if (a.type === "suggested_reviewers") {
        return a as SuggestedReviewersArtefact;
      }
    }
    return null;
  }, [artefacts]);

  const findingsBySignalId = useMemo(() => {
    const map = new Map<string, SignalFindingContent>();
    for (const a of artefacts) {
      if (a.type === "signal_finding") {
        const c = a.content as SignalFindingContent;
        map.set(c.signal_id, c);
      }
    }
    return map;
  }, [artefacts]);

  const allSignals = signalsQuery.data?.signals ?? [];
  // Match web: split session_problem evidence from main Signals list.
  const signals = allSignals.filter(
    (s) =>
      !(
        s.source_product === "session_replay" &&
        s.source_type === "session_problem"
      ),
  );

  const handleStartTask = useCallback(
    (feedback?: string) => {
      if (!report) return;
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      setCreatePrFeedbackOpen(false);
      tracker.signalAction({
        report_id: report.id,
        report_title: report.title ?? null,
        report_age_hours: computeReportAgeHours(report.created_at),
        action_type: "create_pr",
        surface: "detail_pane",
        is_bulk: false,
        bulk_size: 1,
        has_feedback: !!feedback,
        ...(feedback ? { feedback_text: feedback.slice(0, 500) } : {}),
      });
      const prompt = buildCreatePrReportPrompt({
        summary: report.summary,
        feedback,
      });
      router.push({
        pathname: "/task",
        params: {
          prompt,
          ...(reportRepo ? { repo: reportRepo } : {}),
          signalReport: report.id,
        },
      });
    },
    [report, router, reportRepo, tracker],
  );

  const handleDismissed = useCallback(
    (result: DismissReportResult) => {
      setDismissOpen(false);
      if (report) {
        const reasonOption = DISMISSAL_REASON_OPTIONS.find(
          (o) => o.value === result.reason,
        );
        const isSnooze =
          reasonOption !== undefined &&
          "snoozesInsteadOfDismiss" in reasonOption &&
          reasonOption.snoozesInsteadOfDismiss === true;
        tracker.signalAction({
          report_id: report.id,
          report_title: report.title ?? null,
          report_age_hours: computeReportAgeHours(report.created_at),
          action_type: isSnooze ? "snooze" : "dismiss",
          surface: "detail_pane",
          is_bulk: false,
          bulk_size: 1,
          ...(isSnooze
            ? {}
            : {
                dismissal_reason: result.reason,
                ...(result.note
                  ? { dismissal_note: result.note.slice(0, 1000) }
                  : {}),
              }),
        });
      }
      if (router.canGoBack()) router.back();
    },
    [router, report, tracker],
  );

  const handleDiscussSubmit = useCallback(
    ({ prompt, question }: { prompt: string; question: string }) => {
      setDiscussOpen(false);
      if (!report) return;
      posthog?.capture("Inbox report action", {
        report_id: report.id,
        report_title: report.title ?? null,
        action_type: "discuss",
        surface: "detail_pane",
        is_bulk: false,
        bulk_size: 1,
        has_question: question.length > 0,
        ...(question.length > 0
          ? { question_text: question.slice(0, 500) }
          : {}),
      });
      router.push({
        pathname: "/task",
        params: {
          prompt,
          ...(reportRepo ? { repo: reportRepo } : {}),
          signalReport: report.id,
        },
      });
    },
    [report, router, reportRepo, posthog],
  );

  if (error) {
    return (
      <View className="flex-1 items-center justify-center bg-background px-4">
        <Text className="mb-4 text-center text-status-error">
          Failed to load report
        </Text>
        <Pressable
          onPress={() => router.back()}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Go back</Text>
        </Pressable>
      </View>
    );
  }

  if (isLoading || !report) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
      </View>
    );
  }

  const updatedAt = new Date(report.updated_at);
  const hoursSince = differenceInHours(new Date(), updatedAt);
  const timeDisplay =
    hoursSince < 24
      ? formatDistanceToNow(updatedAt, { addSuffix: true })
      : format(updatedAt, "MMM d, yyyy");

  const isReady = report.status === "ready";

  const isAwaitingInput =
    report.status === "pending_input" ||
    (report.status === "ready" &&
      report.actionability === "requires_human_input");

  const canStartTask =
    isAwaitingInput ||
    (report.status === "ready" &&
      report.actionability === "immediately_actionable" &&
      report.already_addressed !== true);

  const alreadyAddressed =
    report.already_addressed ??
    actionabilityJudgment?.already_addressed ??
    false;

  const primaryActionLabel = isAwaitingInput
    ? "Implement as new task"
    : "Start task";

  return (
    <>
      <ScrollView
        className="flex-1 bg-background"
        contentContainerStyle={{
          paddingHorizontal: 16,
          paddingTop: 16,
          paddingBottom: insets.bottom + 100,
        }}
        onScroll={handleScroll}
        scrollEventThrottle={250}
      >
        {/* Badges row */}
        <View className="mb-3 flex-row flex-wrap items-center gap-1.5">
          <StatusBadge status={report.status} />
          {report.priority && <PriorityBadge priority={report.priority} />}
          {report.actionability && (
            <ActionabilityBadge value={report.actionability} />
          )}
          {report.is_suggested_reviewer && (
            <View className="rounded bg-status-warning/20 px-2 py-1">
              <Text className="font-medium text-[12px] text-status-warning">
                For you
              </Text>
            </View>
          )}
        </View>

        {/* Title */}
        <Text className="mb-2 font-semibold text-[18px] text-gray-12">
          {report.title ?? "Untitled signal"}
        </Text>

        {/* Meta row */}
        <View className="mb-4 flex-row items-center gap-3">
          <View className="flex-row items-center gap-1">
            <Lightning size={13} color={themeColors.gray[9]} />
            <Text className="text-[12px] text-gray-9">
              {report.signal_count} signal{report.signal_count !== 1 ? "s" : ""}
            </Text>
          </View>
          <Text className="text-[12px] text-gray-9">Updated {timeDisplay}</Text>
          {report.implementation_pr_url ? (
            <View className="ml-auto">
              <PrStatusBadge
                prUrl={report.implementation_pr_url}
                hideWhenUnresolved
                size="sm"
              />
            </View>
          ) : null}
        </View>

        {/* Failed warning */}
        {report.status === "failed" && (
          <View className="mb-4 flex-row items-start gap-2 rounded-lg bg-status-error/10 p-3">
            <Warning size={16} color={themeColors.status.error} weight="fill" />
            <View className="flex-1">
              <Text className="font-medium text-[13px] text-status-error">
                Report processing failed
              </Text>
              <Text className="mt-0.5 text-[12px] text-status-error">
                There was an issue processing this report. It may be retried
                automatically.
              </Text>
            </View>
          </View>
        )}

        {/* Already-addressed banner */}
        {alreadyAddressed && (
          <View className="mb-4 flex-row items-start gap-2 rounded-lg border border-status-warning/40 bg-status-warning/10 p-3">
            <Warning
              size={16}
              color={themeColors.status.warning}
              weight="fill"
            />
            <Text className="flex-1 text-[13px] text-status-warning">
              This issue may already be addressed in recent code changes.
            </Text>
          </View>
        )}

        {/* Summary */}
        {report.summary && (
          <View className="mb-4" style={{ opacity: isReady ? 1 : 0.7 }}>
            <MarkdownText
              content={formatSignalReportSummaryMarkdown(report.summary)}
            />
          </View>
        )}

        {/* Suggested reviewers */}
        {reviewerArtefact && (
          <SuggestedReviewers
            reportId={report.id}
            artefact={reviewerArtefact}
            meUuid={me?.uuid}
            fireAction={fireReviewerAction}
          />
        )}

        {/* Signals */}
        {signals.length > 0 && (
          <View className="mb-4">
            <Pressable
              onPress={handleToggleSignals}
              hitSlop={6}
              accessibilityRole="button"
              accessibilityState={{ expanded: signalsExpanded }}
              className="mb-2 flex-row items-center gap-1.5 self-start py-1 active:opacity-60"
            >
              {signalsExpanded ? (
                <CaretDown size={14} color={themeColors.gray[12]} />
              ) : (
                <CaretRight size={14} color={themeColors.gray[12]} />
              )}
              <Text className="font-semibold text-[14px] text-gray-12">
                Signals ({signals.length})
              </Text>
            </Pressable>
            {signalsExpanded && (
              <View className="gap-2">
                {signals.map((signal) => (
                  <SignalCard
                    key={signal.signal_id}
                    signal={signal}
                    finding={findingsBySignalId.get(signal.signal_id)}
                  />
                ))}
              </View>
            )}
          </View>
        )}
        {signalsQuery.isLoading && (
          <Text className="text-[12px] text-gray-9">Loading signals…</Text>
        )}

        {/* Activity log */}
        <ReportActivity reportId={report.id} artefacts={artefacts} />
      </ScrollView>

      <View
        className="absolute inset-x-0 flex-row flex-wrap items-center justify-center gap-3 px-4"
        style={{ bottom: insets.bottom + 16 }}
        pointerEvents="box-none"
      >
        <Pressable
          onPress={() => setDismissOpen(true)}
          accessibilityLabel="Dismiss report"
          className="flex-row items-center gap-2 rounded-full border border-gray-6 bg-background px-4 py-3.5 shadow-lg active:opacity-80"
        >
          <ThumbsDown size={16} color={themeColors.gray[11]} weight="fill" />
          <Text className="font-semibold text-[15px] text-gray-11">
            Dismiss
          </Text>
        </Pressable>

        <Pressable
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setDiscussOpen(true);
          }}
          accessibilityLabel="Discuss report"
          className="flex-row items-center gap-2 rounded-full border border-gray-6 bg-background px-4 py-3.5 shadow-lg active:opacity-80"
        >
          <ChatCircle size={16} color={themeColors.gray[11]} weight="fill" />
          <Text className="font-semibold text-[15px] text-gray-11">
            Discuss
          </Text>
        </Pressable>

        {canStartTask && (
          <View className="flex-row items-center overflow-hidden rounded-full bg-accent-9 shadow-lg">
            <Pressable
              onPress={() => handleStartTask()}
              className="flex-row items-center gap-2 py-3.5 pr-3 pl-4 active:opacity-80"
            >
              {isAwaitingInput ? (
                <Plus size={18} color="#ffffff" weight="bold" />
              ) : (
                <Play size={18} color="#ffffff" weight="fill" />
              )}
              <Text className="font-semibold text-[15px] text-white">
                {primaryActionLabel}
              </Text>
            </Pressable>
            <View className="h-6 w-px bg-white/25" />
            <Pressable
              onPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                setCreatePrFeedbackOpen(true);
              }}
              accessibilityLabel="Add feedback"
              className="py-3.5 pr-4 pl-3 active:opacity-80"
            >
              <CaretDown size={16} color="#ffffff" weight="bold" />
            </Pressable>
          </View>
        )}
      </View>

      <DismissReportSheet
        visible={dismissOpen}
        reportId={report.id}
        reportTitle={report.title?.trim() ? report.title : "Untitled signal"}
        onClose={() => setDismissOpen(false)}
        onDismissed={handleDismissed}
      />

      <DiscussReportSheet
        visible={discussOpen}
        reportId={report.id}
        reportTitle={report.title}
        onClose={() => setDiscussOpen(false)}
        onSubmit={handleDiscussSubmit}
      />

      <CreatePrFeedbackSheet
        visible={createPrFeedbackOpen}
        isAwaitingInput={isAwaitingInput}
        onClose={() => setCreatePrFeedbackOpen(false)}
        onSubmit={handleStartTask}
      />
    </>
  );
}
