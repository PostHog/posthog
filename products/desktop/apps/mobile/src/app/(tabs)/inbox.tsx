import { buildInboxViewedProperties } from "@posthog/core/inbox/engagement";
import { INBOX_PIPELINE_STATUSES } from "@posthog/core/inbox/reportFiltering";
import type { InboxReviewerScope } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ArchivedReportList } from "@/features/inbox/components/ArchivedReportList";
import { FilterSheet } from "@/features/inbox/components/FilterSheet";
import { FloatingInboxHeader } from "@/features/inbox/components/FloatingInboxHeader";
import {
  type InboxViewMode,
  InboxViewToggle,
} from "@/features/inbox/components/InboxViewToggle";
import { ReportList } from "@/features/inbox/components/ReportList";
import { ReviewerFilterSheet } from "@/features/inbox/components/ReviewerFilterSheet";
import { TinderView } from "@/features/inbox/components/TinderView";
import {
  useArchivedReports,
  useInboxReports,
} from "@/features/inbox/hooks/useInboxReports";
import {
  decidedIds,
  useDismissedReportsStore,
} from "@/features/inbox/stores/dismissedReportsStore";
import { useInboxFilterStore } from "@/features/inbox/stores/inboxFilterStore";
import { useInboxStore } from "@/features/inbox/stores/inboxStore";
import { useIntegrations } from "@/features/tasks/hooks/useIntegrations";
import { ANALYTICS_EVENTS, useAnalytics } from "@/lib/analytics";

export default function InboxScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { reports, totalCount, isFetching, isLoading, error } =
    useInboxReports();
  const [filterOpen, setFilterOpen] = useState(false);
  const [reviewerOpen, setReviewerOpen] = useState(false);
  const [viewMode, setViewMode] = useState<InboxViewMode>("list");
  const archived = useArchivedReports({ enabled: viewMode === "archive" });
  const reviewerFilterCount = useInboxFilterStore(
    (s) => s.suggestedReviewerFilter.length,
  );
  const sourceProductFilter = useInboxFilterStore((s) => s.sourceProductFilter);
  const statusFilter = useInboxFilterStore((s) => s.statusFilter);
  const priorityFilter = useInboxFilterStore((s) => s.priorityFilter);
  const suggestedReviewerFilter = useInboxFilterStore(
    (s) => s.suggestedReviewerFilter,
  );

  const analytics = useAnalytics();
  // Fire INBOX_VIEWED once per focus when the report list has settled. We
  // bump a focus counter on every focus so the useEffect re-runs even when
  // the data is already cached (no loading/filter/list change to trigger it
  // on its own), then guard against double-fires within the same focus via
  // a ref keyed on the focus-version we last fired for.
  const [focusVersion, setFocusVersion] = useState(0);
  useFocusEffect(
    useCallback(() => {
      setFocusVersion((v) => v + 1);
    }, []),
  );
  const viewedFiredForFocusRef = useRef<number | null>(null);
  useEffect(() => {
    if (focusVersion === 0) return;
    if (isLoading) return;
    if (viewedFiredForFocusRef.current === focusVersion) return;
    viewedFiredForFocusRef.current = focusVersion;
    analytics.track(
      ANALYTICS_EVENTS.INBOX_VIEWED,
      buildInboxViewedProperties({
        visibleReports: reports,
        totalCount,
        filters: {
          surface: "mobile",
          sourceProductFilter,
          statusFilter,
          suggestedReviewerFilter,
          priorityFilter,
          defaultStatusFilter: INBOX_PIPELINE_STATUSES,
        },
      }),
    );
  }, [
    analytics,
    focusVersion,
    isLoading,
    reports,
    totalCount,
    sourceProductFilter,
    statusFilter,
    suggestedReviewerFilter,
    priorityFilter,
  ]);

  // ── Tinder mode data ──────────────────────────────────────────────────────
  const decided = useDismissedReportsStore(decidedIds);
  const setCurrentIndex = useInboxStore((s) => s.setCurrentIndex);
  const setLastVisibleReportIds = useInboxStore(
    (s) => s.setLastVisibleReportIds,
  );
  const { repositoryOptions } = useIntegrations();

  // Snapshot the visible-list IDs into the store so the detail screen can
  // record rank/list_size on OPENED. Only the list view exposes a rank — the
  // tinder card stack swaps cards in place.
  useEffect(() => {
    if (viewMode === "list") {
      setLastVisibleReportIds(reports.map((r) => r.id));
    } else {
      setLastVisibleReportIds([]);
    }
  }, [viewMode, reports, setLastVisibleReportIds]);

  // Same data as the list view, excluding already-decided reports.
  const tinderReports = useMemo(
    () => reports.filter((r) => !decided.includes(r.id)),
    [reports, decided],
  );

  // Reset card index when switching to tinder mode
  useEffect(() => {
    if (viewMode === "tinder") {
      setCurrentIndex(0);
    }
  }, [viewMode, setCurrentIndex]);

  const hasActiveFilters =
    sourceProductFilter.length > 0 ||
    priorityFilter.length > 0 ||
    statusFilter.length < INBOX_PIPELINE_STATUSES.length ||
    suggestedReviewerFilter.length > 0;

  // Coarse reviewer scope. Mobile has no scope control yet, so a non-empty
  // reviewer filter reads as "teammate" without leaking a specific UUID.
  const triageScope: InboxReviewerScope =
    suggestedReviewerFilter.length > 0 ? "teammate" : "entire-project";

  // Bracket tinder mode with triage_started / triage_ended so we can measure
  // how many cards users clear before exiting. The live ref lets the cleanup
  // read the current decided count without re-firing the pair on every swipe;
  // it is set in an effect so we don't mutate refs during render.
  const triageLiveRef = useRef({ decided: 0 });
  useEffect(() => {
    triageLiveRef.current.decided = decided.length;
  });
  // Snapshot filters/queue at tinder-mode entry; swipes don't re-fire the pair.
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional snapshot
  useEffect(() => {
    if (viewMode !== "tinder") return;
    const startedAt = Date.now();
    const entry = {
      queueSize: tinderReports.length,
      initialDecided: decided.length,
      hasActiveFilters,
      scope: triageScope,
    };
    analytics.track(ANALYTICS_EVENTS.INBOX_TRIAGE_STARTED, {
      queue_size: entry.queueSize,
      has_active_filters: entry.hasActiveFilters,
      scope: entry.scope,
    });
    return () => {
      const reviewed = Math.max(
        0,
        triageLiveRef.current.decided - entry.initialDecided,
      );
      analytics.track(ANALYTICS_EVENTS.INBOX_TRIAGE_ENDED, {
        queue_size: entry.queueSize,
        has_active_filters: entry.hasActiveFilters,
        scope: entry.scope,
        reports_reviewed: reviewed,
        duration_ms: Date.now() - startedAt,
        end_reason: reviewed >= entry.queueSize ? "completed" : "exited",
      });
    };
  }, [viewMode, analytics]);

  // ── List mode handlers ────────────────────────────────────────────────────
  const handleReportPress = useCallback(
    (report: SignalReport) => {
      router.push(`/inbox/${report.id}`);
    },
    [router],
  );

  // Header occupies insets.top + 6 (top pad) + 40 (MenuButton) + 8 (bottom
  // pad), plus a small buffer so the first row isn't hugging the fade edge.
  const headerHeight = insets.top + 60;

  return (
    <View className="flex-1 bg-background">
      {viewMode === "list" ? (
        <ReportList
          onReportPress={handleReportPress}
          contentInsetTop={headerHeight}
        />
      ) : viewMode === "archive" ? (
        <ArchivedReportList
          onReportPress={handleReportPress}
          contentInsetTop={headerHeight}
        />
      ) : (
        <View style={{ paddingTop: headerHeight }} className="flex-1">
          <TinderView
            reports={tinderReports}
            repositoryOptions={repositoryOptions}
            isLoading={isLoading}
          />
        </View>
      )}

      <FloatingInboxHeader
        isFetching={viewMode === "archive" ? archived.isFetching : isFetching}
        hasError={viewMode === "archive" ? !!archived.error : !!error}
        reviewerFilterCount={reviewerFilterCount}
        showFilters={viewMode === "list"}
        onReviewerPress={() => setReviewerOpen(true)}
        onFilterPress={() => setFilterOpen(true)}
      />

      <InboxViewToggle mode={viewMode} onModeChange={setViewMode} />

      <FilterSheet visible={filterOpen} onClose={() => setFilterOpen(false)} />
      <ReviewerFilterSheet
        visible={reviewerOpen}
        onClose={() => setReviewerOpen(false)}
      />
    </View>
  );
}
